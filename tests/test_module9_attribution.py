"""Module 9 §9.3 — reporting reads Module 7's attribution; it never re-matches
payments or re-derives credit. Covers direct / indirect / multi-case / no-match
outcomes and one end-to-end run of the real reconciliation pipeline.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from tests.module9_helpers import set_recovery
from torque.enums import CaseStatus, LegType, RecoveryType
from torque.reconciliation.reconcile import reconcile_event
from torque.reporting import metrics

_A = RecoveryType.AGENT_ASSISTED


def _pd(make_case, m, cp, *, amount, **kw):
    return make_case(
        merchant=m, counterparty=cp, leg=LegType.PAYMENT_DEGRADATION,
        context={"gateway": "razorpay"}, amount_at_risk=Decimal(str(amount)), **kw,
    )


def test_report_reflects_recovery_type_verbatim(db, make_merchant, make_case):
    m = make_merchant()
    direct = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                       context={"gateway": "razorpay"}, amount_at_risk=Decimal("1000.00"))
    indirect = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                         context={"gateway": "razorpay"}, amount_at_risk=Decimal("2000.00"))
    ambiguous = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                          context={"gateway": "razorpay"}, amount_at_risk=Decimal("3000.00"))
    self_paid = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                          context={"gateway": "razorpay"}, amount_at_risk=Decimal("4000.00"))

    # Module 7 already decided these — Module 9 just tallies them.
    set_recovery(db, direct, recovery_type=_A, amount="1000.00")
    set_recovery(db, indirect, recovery_type=_A, amount="2000.00")
    set_recovery(db, ambiguous, recovery_type=RecoveryType.AMBIGUOUS, amount="3000.00")
    set_recovery(db, self_paid, recovery_type=RecoveryType.SELF_RECOVERED,
                 amount="4000.00", status=CaseStatus.CANCELLED)

    s = metrics.recovery_summary(db, m.merchant_id)
    # AGENT_ASSISTED + AMBIGUOUS credited; SELF_RECOVERED not
    assert s.recovered_amount == Decimal("6000.00")
    assert s.self_recovered_amount == Decimal("4000.00")

    by_type = {r.recovery_type: r for r in metrics.recovery_by_recovery_type(db, m.merchant_id)}
    assert by_type["AGENT_ASSISTED"].recovered_amount == Decimal("3000.00")
    assert by_type["AMBIGUOUS"].recovered_amount == Decimal("3000.00")
    assert by_type["SELF_RECOVERED"].recovered_amount == Decimal("4000.00")


def test_unattributed_open_cases_are_not_recovered(db, make_merchant, make_case):
    m = make_merchant()
    for amt in ("1000.00", "2000.00"):
        make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                  context={"gateway": "razorpay"}, amount_at_risk=Decimal(amt))
    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.recovered_amount == Decimal("0.00")
    assert s.revenue_at_risk == Decimal("3000.00")
    assert s.recovery_rate == Decimal("0")


def test_multi_case_credit_weight_is_surfaced_not_recomputed(
    db, make_merchant, make_counterparty, make_case, make_action
):
    m = make_merchant()
    cp = make_counterparty()
    big = _pd(make_case, m, cp, amount="8000.00", status=CaseStatus.PLAYBOOK_ACTIVE)
    small = _pd(make_case, m, cp, amount="2000.00", status=CaseStatus.PLAYBOOK_ACTIVE)
    # one merged Action across both cases (weights 0.8 / 0.2), as Module 6 would
    from decimal import Decimal as D

    from torque.enums import Actor
    from torque.events import Attribution, write_action_and_event
    from torque.models import Action

    action = Action(
        merchant_id=m.merchant_id, primary_case_id=big.case_id, run_id=None,
        action_type="SEND_WHATSAPP", channel="whatsapp",
        executed_at=datetime(2026, 9, 9, tzinfo=UTC), outcome="SUCCESS",
    )
    write_action_and_event(
        db, action=action, actor=Actor.SYSTEM,
        attributions=[
            Attribution(case_id=big.case_id, is_primary=True, credit_weight=D("0.80000")),
            Attribution(case_id=small.case_id, is_primary=False, credit_weight=D("0.20000")),
        ],
    )
    set_recovery(db, big, recovery_type=_A, amount="8000.00")
    set_recovery(db, small, recovery_type=_A, amount="2000.00")

    d_big = metrics.case_detail(db, m.merchant_id, big.case_id)
    d_small = metrics.case_detail(db, m.merchant_id, small.case_id)
    assert d_big.actions[0].credit_weight == D("0.80000")
    assert d_small.actions[0].credit_weight == D("0.20000")
    # both fully recovered in the summary
    assert metrics.recovery_summary(db, m.merchant_id).recovered_amount == Decimal("10000.00")


def test_end_to_end_reconcile_then_report(
    db, make_merchant, make_counterparty, make_case, make_event
):
    """Run the REAL Module 7 pipeline (indirect match + 24h window) and confirm
    the report reflects exactly what reconciliation wrote."""
    m = make_merchant(merchant_id="acc_e2e_rep")
    cp = make_counterparty(phone="+919812345000", email="e2e@x.test")
    case = _pd(make_case, m, cp, amount="499.00", status=CaseStatus.PLAYBOOK_ACTIVE)

    # a Torque action within the attribution window → AGENT_ASSISTED
    from torque.enums import Actor
    from torque.events import Attribution, write_action_and_event
    from torque.models import Action

    act = Action(
        merchant_id=m.merchant_id, primary_case_id=case.case_id, run_id=None,
        action_type="SEND_WHATSAPP", channel="whatsapp",
        executed_at=datetime.now(UTC), outcome="SUCCESS",
    )
    write_action_and_event(
        db, action=act, actor=Actor.SYSTEM,
        attributions=[
            Attribution(
                case_id=case.case_id, is_primary=True, credit_weight=Decimal("1.00000")
            )
        ],
    )

    body = json.loads(razorpay_payment_body(
        event="payment.captured", amount_paise=49900,
        email="e2e@x.test", contact="+919812345000",
    ))
    ev = make_event(m, type="payment.captured", raw_payload=body)
    reconcile_event(db, event_id=ev.event_id)

    db.refresh(case)
    assert case.status is CaseStatus.RECOVERED
    assert case.recovery_type is RecoveryType.AGENT_ASSISTED

    s = metrics.recovery_summary(db, m.merchant_id)
    assert s.recovered_amount == Decimal("499.00")
    assert s.recovered_case_count == 1
    detail = metrics.case_detail(db, m.merchant_id, case.case_id)
    assert detail.recovery_type == "AGENT_ASSISTED"
    assert detail.recovered_amount == Decimal("499.00")
    # PAYMENT_RECONCILED shows in the explainability stream
    stream = metrics.case_event_stream(db, m.merchant_id, case.case_id)
    assert any(e.event_type == "PAYMENT_RECONCILED" for e in stream)
    assert stream == sorted(stream, key=lambda e: e.event_seq_id)


def test_reporting_adds_no_reconciliation_writes(db, make_merchant, make_case):
    """Calling the report must not create Actions / CaseEvents / mutate cases."""
    from torque.models import Action, CaseEvent

    m = make_merchant()
    c = make_case(merchant=m, leg=LegType.PAYMENT_DEGRADATION,
                  context={"gateway": "razorpay"}, amount_at_risk=Decimal("1000.00"))
    set_recovery(db, c, recovery_type=_A, amount="1000.00")
    before_actions = db.scalar(select(Action).with_only_columns(Action.action_id).limit(1))
    ev_count = len(db.scalars(select(CaseEvent)).all())

    metrics.recovery_report(db, m.merchant_id)
    metrics.recovery_over_time(db, m.merchant_id)
    metrics.operational_exceptions(db, m.merchant_id)

    assert len(db.scalars(select(CaseEvent)).all()) == ev_count
    assert db.scalar(select(Action).with_only_columns(Action.action_id).limit(1)) == before_actions
