"""Application-layer multi-tenancy (Blueprint Section 2.1).

Every tenant-scoped table carries `merchant_id`. `TenantScope` is the single
sanctioned data-access path: it always injects `merchant_id` into reads and
stamps it on writes, and it *refuses* to build a query for a globally-scoped
model so that touching `Counterparty` / static config is always a deliberate,
visible act (`unscoped()` escape hatch) rather than an accident.

Roadmap: Postgres Row-Level Security as defense-in-depth. Not built now.
"""

from __future__ import annotations

from typing import TypeVar

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from torque.db.base import TenantScoped
from torque.exceptions import (
    CrossTenantWriteError,
    NonTenantModelError,
    TenantScopeError,
)

T = TypeVar("T")


def is_tenant_scoped(model: type) -> bool:
    return isinstance(model, type) and issubclass(model, TenantScoped)


class TenantScope:
    """A merchant-bound facade over a SQLAlchemy `Session`."""

    def __init__(self, session: Session, merchant_id: str) -> None:
        if not merchant_id:
            raise TenantScopeError("merchant_id is required to open a TenantScope")
        self._session = session
        self.merchant_id = merchant_id

    # --- reads --------------------------------------------------------------

    def select(self, model: type[T]) -> Select[tuple[T]]:
        """A `Select` already filtered to this merchant.

        Raises for globally-scoped models — use `unscoped()` for those.
        """
        if not is_tenant_scoped(model):
            raise NonTenantModelError(
                f"{model.__name__} is not tenant-scoped; use TenantScope.unscoped()"
            )
        return select(model).where(model.merchant_id == self.merchant_id)

    def get(self, model: type[T], pk) -> T | None:
        """Fetch by primary key, returning None if the row belongs to another
        merchant (never another tenant's data, even on a direct id lookup)."""
        obj = self._session.get(model, pk)
        if obj is None:
            return None
        if is_tenant_scoped(model) and getattr(obj, "merchant_id", None) != self.merchant_id:
            return None
        return obj

    def all(self, model: type[T]) -> list[T]:
        return list(self._session.scalars(self.select(model)).all())

    # --- writes -----------------------------------------------------------

    def add(self, obj) -> None:
        """Stamp `merchant_id` on tenant-scoped objects; reject cross-tenant."""
        if is_tenant_scoped(type(obj)):
            current = getattr(obj, "merchant_id", None)
            if current is None:
                obj.merchant_id = self.merchant_id
            elif current != self.merchant_id:
                raise CrossTenantWriteError(
                    f"{type(obj).__name__}.merchant_id={current!r} written through "
                    f"scope for merchant {self.merchant_id!r}"
                )
        self._session.add(obj)

    def add_all(self, objs) -> None:
        for obj in objs:
            self.add(obj)

    def delete(self, obj) -> None:
        if (
            is_tenant_scoped(type(obj))
            and getattr(obj, "merchant_id", None) != self.merchant_id
        ):
            raise CrossTenantWriteError(
                f"cannot delete {type(obj).__name__} owned by "
                f"{getattr(obj, 'merchant_id', None)!r} through scope for "
                f"{self.merchant_id!r}"
            )
        self._session.delete(obj)

    # --- escape hatch ---------------------------------------------------

    def unscoped(self) -> Session:
        """The raw session, for `Counterparty` and static config only.

        Named and returned explicitly so that every non-tenant access is
        greppable in review.
        """
        return self._session

    # --- passthrough --------------------------------------------------

    def flush(self) -> None:
        self._session.flush()

    def commit(self) -> None:
        self._session.commit()

    def rollback(self) -> None:
        self._session.rollback()
