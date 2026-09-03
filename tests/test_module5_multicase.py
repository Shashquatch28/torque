"""Module 5 — multi-case context rendering & attribution (Blueprint §4.4 / §5).

The Outreach Coordinator merge trigger is Module 6 (deferred), so the live loop
renders single-case; these tests exercise the merged-render contract directly and
prove the one-ledger `ActionCase` attribution holds for a merged action.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import select

from torque.enums import ActionOutcome, ActionType, Actor, LegType
from torque.events import write_action_and_event
from torque.events.case_event_writer import Attribution
from torque.execution.rendering import multi_case_context, resolve_template
from torque.models import Action, ActionCase
from torque.policy.catalog import CATALOG_BY_ID, PLAYBOOK_GENERIC_CART_NUDGE


def _cart_nudge_first_node():
    graph = CATALOG_BY_ID[PLAYBOOK_GENERIC_CART_NUDGE].steps_graph
    return next(n for n in graph["nodes"] if n["id"] == graph["entry"])


def test_single_case_uses_single_template():
    node = _cart_nudge_first_node()
    template, defer = resolve_template(node, case_count=1)
    assert template == "cart_nudge"
    assert defer is False


def test_merged_uses_multi_case_template():
    node = _cart_nudge_first_node()
    template, defer = resolve_template(node, case_count=2)
    assert template == "cart_nudge_multi"  # the node declares one
    assert defer is False


def test_merged_without_multi_template_defers():
    node = {"id": "x", "action_template": {"type": "SEND_EMAIL"}, "timing_offset_hours": 0,
            "params": {"template": "solo"}}
    template, defer = resolve_template(node, case_count=2)
    assert template == "solo"
    assert defer is True  # Module 5 must defer the secondary case, never drop it


def test_multi_case_context_combines_amounts(db, make_case, make_merchant, make_counterparty):
    m, cp = make_merchant(), make_counterparty()
    c1 = make_case(
        merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={},
        amount_at_risk=Decimal("1000.00"),
    )
    c2 = make_case(
        merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={},
        amount_at_risk=Decimal("2500.00"),
    )
    ctx = multi_case_context([c1, c2])
    assert ctx["is_merged"] is True
    assert ctx["combined_amount"] == "3500.00"
    assert {e["case_id"] for e in ctx["cases"]} == {str(c1.case_id), str(c2.case_id)}


def test_multi_case_context_rejects_superseded(db, make_case, make_merchant, make_counterparty):
    m, cp = make_merchant(), make_counterparty()
    survivor = make_case(merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={})
    narrower = make_case(merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={})
    narrower.superseded_by_case_id = survivor.case_id
    db.flush()
    with pytest.raises(ValueError, match="superseded"):
        multi_case_context([survivor, narrower])


def test_merged_action_attribution_reuses_action_case(
    db, make_case, make_merchant, make_counterparty
):
    """A merged outreach writes ONE Action with an ActionCase per case — the
    existing single-ledger attribution (D-016), not a second model."""
    m, cp = make_merchant(), make_counterparty()
    c1 = make_case(merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={})
    c2 = make_case(merchant=m, counterparty=cp, leg=LegType.B2B_RECEIVABLE, context={})
    action = Action(
        merchant_id=m.merchant_id, primary_case_id=c1.case_id, run_id=None,
        action_type=ActionType.SEND_EMAIL, channel="email",
        executed_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
        outcome=ActionOutcome.SUCCESS,
    )
    write_action_and_event(
        db, action=action, actor=Actor.AGENT,
        attributions=[
            Attribution(case_id=c1.case_id, is_primary=True, credit_weight=Decimal("0.60000")),
            Attribution(case_id=c2.case_id, is_primary=False, credit_weight=Decimal("0.40000")),
        ],
    )
    rows = db.scalars(select(ActionCase).where(ActionCase.action_id == action.action_id)).all()
    assert {r.case_id for r in rows} == {c1.case_id, c2.case_id}
    assert sum(r.credit_weight for r in rows) == Decimal("1.00000")
