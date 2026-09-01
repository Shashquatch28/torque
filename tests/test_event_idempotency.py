"""Blueprint Section 2.5 — Event.idempotency_key (from X-Razorpay-Event-Id) is
unique; a duplicate is rejected by the database."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError

from torque.models import Event


def test_duplicate_idempotency_key_rejected(db, make_merchant):
    m = make_merchant()
    db.add(
        Event(
            merchant_id=m.merchant_id,
            type="payment.failed",
            idempotency_key="evt_ABC123",
            raw_payload={},
        )
    )
    db.flush()
    db.add(
        Event(
            merchant_id=m.merchant_id,
            type="payment.captured",
            idempotency_key="evt_ABC123",
            raw_payload={},
        )
    )
    with pytest.raises(IntegrityError):
        db.flush()


def test_distinct_keys_coexist(db, make_merchant):
    m = make_merchant()
    db.add_all(
        [
            Event(
                merchant_id=m.merchant_id,
                type="payment.failed",
                idempotency_key="evt_1",
                raw_payload={},
            ),
            Event(
                merchant_id=m.merchant_id,
                type="payment.failed",
                idempotency_key="evt_2",
                raw_payload={},
            ),
        ]
    )
    db.flush()
