"""FastAPI request dependencies.

`get_db` yields a session from the sanctioned `SessionLocal` (so the flush
guards from `torque.models.guards` are wired) and commits it once the handler
returns cleanly. The webhook handler builds its own `TenantScope` over this
session from the path `merchant_id` — every ingestion write goes through the
tenancy facade (INV-01), never `TenantScope.unscoped()`.

Tests override `get_db` with the joined-transaction session from the harness,
which manages its own lifecycle (no commit, rolled back afterwards).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from torque.db.session import SessionLocal


def get_db() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
