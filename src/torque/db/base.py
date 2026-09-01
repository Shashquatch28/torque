"""Declarative base with a deterministic naming convention.

A fixed naming convention keeps Alembic migrations stable and reviewable — every
index / constraint has a predictable name regardless of when it was generated.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TenantScoped:
    """Marker mixin. A model that inherits this MUST declare a non-null
    ``merchant_id`` column and is only reachable through :class:`TenantScope`.

    Deliberately NOT inherited by ``Counterparty`` (and, in later milestones,
    ``MacCodeRegistry`` / ``ChannelRateCard``) — those are global identity /
    static config, scoped through ``Merchant_Counterparty`` instead (R3).
    """

    __tenant_scoped__ = True
