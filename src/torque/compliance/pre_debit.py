"""Pure pre-debit gap predicate — Blueprint Section 3 / Module 6 guardrail.

Compliance reference: RBI Digital Payments - E-Mandate Framework, 2026.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.models.pre_debit_notification import PreDebitNotification

# RBI requires the pre-debit notification to precede EACH debit/retry by at
# least 24h. A hard legal floor — not a tunable PolicyConfig value.
PRE_DEBIT_MIN_GAP_HOURS = 24


def gap_satisfied(
    session: Session,
    *,
    case_id: uuid.UUID,
    next_attempt_number: int,
    now: datetime,
) -> bool:
    """True iff a pre-debit notification for exactly this `next_attempt_number`
    was sent at least `PRE_DEBIT_MIN_GAP_HOURS` before `now`.

    Mirrors the Section 3 EXISTS check:
        EXISTS(SELECT 1 FROM pre_debit_notification
               WHERE case_id = X AND covers_attempt_number = next_attempt
               AND now() - notified_at >= 24h)
    """
    cutoff = now - timedelta(hours=PRE_DEBIT_MIN_GAP_HOURS)
    hit = session.scalar(
        select(PreDebitNotification.notification_id)
        .where(PreDebitNotification.case_id == case_id)
        .where(PreDebitNotification.covers_attempt_number == next_attempt_number)
        .where(PreDebitNotification.notified_at <= cutoff)
        .limit(1)
    )
    return hit is not None
