"""Milestone 7b — a failure anywhere in the ingestion write set leaves nothing.

`buffer.resolve_buffered_event` / `cases.create_or_attach_case` do not own a
transaction — the Celery task's `session_scope()` does, and rolls the whole
thing back on any exception. Here the task's transaction boundary is simulated
with a nested SAVEPOINT: the originating `Event` is written *before* it (as the
M7a webhook would, in its own committed transaction); the buffer path runs
*inside* it; on failure the SAVEPOINT is rolled back and we assert that no
partial case / counterparty / merge / budget survived and the `Event` is still
unprocessed.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from tests.conftest import razorpay_payment_body
from torque.exceptions import ContextValidationError
from torque.ingestion import cases as cases_mod
from torque.ingestion.buffer import resolve_buffered_event
from torque.models import CardRetryBudget, Counterparty, Event, RevenueLeakCase


def _failed(make_event, m, **body):
    return make_event(
        m, type="payment.failed", raw_payload=json.loads(razorpay_payment_body(**body))
    )


def _counts(db):
    return (
        len(db.scalars(select(RevenueLeakCase)).all()),
        len(db.scalars(select(Counterparty)).all()),
        len(db.scalars(select(CardRetryBudget)).all()),
    )


def test_failure_during_card_seed_rolls_everything_back(db, make_merchant, make_event, monkeypatch):
    m = make_merchant()
    ev = _failed(make_event, m, method="card", token_id="token_BOOM")

    def _boom(*a, **k):
        raise RuntimeError("card seed failed")

    monkeypatch.setattr(cases_mod, "seed_card_retry_budget", _boom)

    savepoint = db.begin_nested()
    with pytest.raises(RuntimeError):
        resolve_buffered_event(db, event_id=ev.event_id)
    savepoint.rollback()

    assert _counts(db) == (0, 0, 0)
    assert db.get(Event, ev.event_id).processed is False


def test_invalid_context_rolls_everything_back(db, make_merchant, make_event, monkeypatch):
    m = make_merchant()
    ev = _failed(make_event, m)

    monkeypatch.setattr(
        "torque.ingestion.cases.payloads.payment_degradation_context",
        lambda payload: {"nonsense": True},  # fails the typed-context guard
    )

    savepoint = db.begin_nested()
    with pytest.raises(ContextValidationError):
        resolve_buffered_event(db, event_id=ev.event_id)
    savepoint.rollback()

    assert _counts(db) == (0, 0, 0)
    assert db.get(Event, ev.event_id).processed is False
