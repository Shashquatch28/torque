"""Engine and session factory.

The `before_flush` / `after_flush` guards from `torque.models.guards` are wired
onto `SessionLocal` here so that every session created through the sanctioned
factory enforces the RevenueLeakCase invariants and CaseEvent append-only rule.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from torque.config import get_settings

engine = create_engine(get_settings().database_url, future=True, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def _install_guards() -> None:
    # Imported lazily to avoid a circular import (guards -> models -> db).
    from torque.models.guards import register_guards

    register_guards(SessionLocal)


_install_guards()


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope: commit on success, roll back on exception."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Session:
    """Return a raw session. Prefer `session_scope()` or `TenantScope`."""
    return SessionLocal()
