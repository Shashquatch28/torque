"""Torque domain exceptions.

Kept in one module so callers can catch `TorqueError` broadly or the specific
subclasses narrowly. All are plain value/So invariant violations — none of them
are recoverable at the data-model layer; they signal a programming error or a
rejected write.
"""

from __future__ import annotations


class TorqueError(Exception):
    """Base class for every Torque domain error."""


# --- Multi-tenancy (Blueprint Section 2.1) -------------------------------------


class TenantScopeError(TorqueError):
    """A tenant-scoped data access was attempted without / across a merchant."""


class CrossTenantWriteError(TenantScopeError):
    """An object belonging to merchant A was written through merchant B's scope."""


class NonTenantModelError(TenantScopeError):
    """A globally-scoped model was passed to the tenant-scoped query path.

    Applies to `Counterparty`, `MacCodeRegistry`, `ChannelRateCard` — these are
    deliberately exempt from `merchant_id` scoping (confirmed R3); relationship
    data is scoped via `Merchant_Counterparty`.
    """


# --- Typed leg context (Blueprint Section 3) ---------------------------------


class ContextValidationError(TorqueError):
    """`RevenueLeakCase.context` failed validation for its `leg_type`."""


# --- CaseEvent (Blueprint Section 2.3 / Section 4) --------------------------


class UnknownEventTypeError(TorqueError):
    """A CaseEvent was written with an `event_type` that has no payload schema."""


class PayloadValidationError(TorqueError):
    """A CaseEvent payload did not match the locked schema for its `event_type`."""


class AppendOnlyViolation(TorqueError):
    """An UPDATE or DELETE was attempted against the append-only CaseEvent log."""


# --- RevenueLeakCase invariants --------------------------------------------


class OwnershipViolation(TorqueError):
    """A field was written by code that does not own it (e.g. Module 7 fields)."""


class MonotonicityViolation(TorqueError):
    """`network_directive` was moved to a less restrictive tier (Section 4)."""


class IllegalTransitionError(TorqueError):
    """A `RevenueLeakCase.status` transition is not in the locked state machine."""


class CohortAlreadyAssignedError(TorqueError):
    """`Merchant_Counterparty.in_control_cohort` is assigned once and immutable."""
