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


# --- Playbook (Blueprint Section 3 / Section 4.2) ---------------------------


class PlaybookValidationError(TorqueError):
    """A `Playbook` version (or a `MerchantPlaybookConfig` override merged onto
    one) failed a save-time validation rule: malformed `steps_graph`, malformed
    `stopping_rules`, or a UPI AutoPay `max_attempts > 3` ceiling (Section 4.2).
    """


class PlaybookNotFoundError(TorqueError):
    """A `MerchantPlaybookConfig` references a `playbook_id` that has no
    published `playbook` version to validate the override against."""


class PlaybookGraphError(TorqueError):
    """A runtime graph-reading helper (`torque.policy.traversal`) was asked for a
    node/edge that does not exist in an already-validated `steps_graph` — a
    programming error, never malformed data (the graph cleared save-time
    validation)."""


# --- Action / ActionCase (Blueprint Section 3 / Section 2.3) ---------------


class ActionAtomicityError(TorqueError):
    """An `Action` was flushed without its correlated `CaseEvent`
    (`ACTION_EXECUTED` / `ACTION_BLOCKED` with a matching `action_id` in the
    payload) in the same transaction.

    Blueprint Section 2.3 frames this as a code-review checklist item; Torque
    strengthens it to a structurally enforced invariant (see the Milestone 5
    intentional-deviations note in `torque.models.guards`)."""


class ActionCaseInvariantError(TorqueError):
    """The `ActionCase` attribution set for an `action_id` is missing, or
    violates: exactly one `is_primary`, `is_primary.case_id ==
    Action.primary_case_id`, or Σ `credit_weight` == Decimal('1.00000')."""


class PromiseTransitionError(TorqueError):
    """A `PromiseToPay.status` change is not a legal transition. Only
    `PENDING -> KEPT` and `PENDING -> BROKEN` are permitted; `KEPT` and
    `BROKEN` are terminal, and a `PromiseToPay` is created `PENDING`."""
