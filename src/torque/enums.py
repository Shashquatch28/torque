"""Complete enum reference — Blueprint v7 Part A Section 4, verbatim.

Every value here is transcribed directly from the blueprint. `root_cause_code`
is deliberately NOT defined here: it is owned by Module 3 (Section 3.1) and
freezing it in Module 1 would create a false contract.

Postgres native ENUM types are created for every enum in migration 0001 so that
later module migrations only reference them. The Python members are the mirror
the application code uses.
"""

from __future__ import annotations

from enum import StrEnum


class LegType(StrEnum):
    PAYMENT_DEGRADATION = "PAYMENT_DEGRADATION"
    CHECKOUT_ABANDONMENT = "CHECKOUT_ABANDONMENT"
    SUBSCRIPTION_FAILURE = "SUBSCRIPTION_FAILURE"
    B2B_RECEIVABLE = "B2B_RECEIVABLE"


class MandateType(StrEnum):
    UPI_AUTOPAY = "UPI_AUTOPAY"
    NACH = "NACH"
    CARD = "CARD"


class CaseStatus(StrEnum):
    """Full state machine in `state_machine.py`. Value set confirmed (R4)."""

    DETECTED = "DETECTED"
    SYSTEMIC_HOLD = "SYSTEMIC_HOLD"
    DIAGNOSING = "DIAGNOSING"
    PLAYBOOK_ACTIVE = "PLAYBOOK_ACTIVE"
    RECOVERED = "RECOVERED"
    PARTIALLY_RECOVERED = "PARTIALLY_RECOVERED"
    EXHAUSTED = "EXHAUSTED"
    ESCALATED_TO_HUMAN = "ESCALATED_TO_HUMAN"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class MacTier(StrEnum):
    TIER_1_HARD_STOP = "TIER_1_HARD_STOP"
    TIER_2_CAPPED_RETRY = "TIER_2_CAPPED_RETRY"
    TIER_3_INSTRUMENT_DEAD = "TIER_3_INSTRUMENT_DEAD"
    TIMED_RETRY = "TIMED_RETRY"


class Network(StrEnum):
    MASTERCARD = "MASTERCARD"
    VISA = "VISA"


class ActionType(StrEnum):
    RETRY_PAYMENT = "RETRY_PAYMENT"
    SEND_PRE_DEBIT_NOTIFICATION = "SEND_PRE_DEBIT_NOTIFICATION"
    SEND_WHATSAPP = "SEND_WHATSAPP"
    SEND_EMAIL = "SEND_EMAIL"
    SEND_SMS = "SEND_SMS"
    GENERATE_PAYMENT_LINK = "GENERATE_PAYMENT_LINK"
    LOG_PROMISE = "LOG_PROMISE"
    ESCALATE_HUMAN = "ESCALATE_HUMAN"
    SYSTEMIC_HOLD = "SYSTEMIC_HOLD"


class ActionOutcome(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    NO_RESPONSE = "NO_RESPONSE"
    BLOCKED_BY_GUARDRAIL = "BLOCKED_BY_GUARDRAIL"


class BlockReason(StrEnum):
    CONSENT_NOT_OBTAINED = "CONSENT_NOT_OBTAINED"
    TEMPLATE_NOT_APPROVED = "TEMPLATE_NOT_APPROVED"
    CARD_NETWORK_LIMIT = "CARD_NETWORK_LIMIT"
    NETWORK_HARD_STOP = "NETWORK_HARD_STOP"
    QUIET_HOURS = "QUIET_HOURS"
    OUTREACH_COORDINATOR_DEFERRED = "OUTREACH_COORDINATOR_DEFERRED"
    SYSTEMIC_HOLD = "SYSTEMIC_HOLD"
    PRE_DEBIT_GAP_NOT_MET = "PRE_DEBIT_GAP_NOT_MET"
    UPI_RETRY_CAP_EXCEEDED = "UPI_RETRY_CAP_EXCEEDED"
    UPI_EXECUTION_WINDOW_CLOSED = "UPI_EXECUTION_WINDOW_CLOSED"
    NACH_CEILING_REACHED = "NACH_CEILING_REACHED"


class CaseEventType(StrEnum):
    STATUS_CHANGED = "STATUS_CHANGED"
    DIAGNOSIS_COMPLETED = "DIAGNOSIS_COMPLETED"
    ACTION_EXECUTED = "ACTION_EXECUTED"
    ACTION_BLOCKED = "ACTION_BLOCKED"
    NETWORK_DIRECTIVE_RECEIVED = "NETWORK_DIRECTIVE_RECEIVED"
    PROMISE_CAPTURED = "PROMISE_CAPTURED"
    PAYMENT_RECONCILED = "PAYMENT_RECONCILED"
    SYSTEMIC_HOLD_APPLIED = "SYSTEMIC_HOLD_APPLIED"
    HUMAN_RESOLVED = "HUMAN_RESOLVED"
    STEP_TRANSITIONED = "STEP_TRANSITIONED"


class Actor(StrEnum):
    SYSTEM = "SYSTEM"
    AGENT = "AGENT"
    HUMAN = "HUMAN"


class RecoveryType(StrEnum):
    AGENT_ASSISTED = "AGENT_ASSISTED"
    SELF_RECOVERED = "SELF_RECOVERED"
    AMBIGUOUS = "AMBIGUOUS"


class PromiseStatus(StrEnum):
    PENDING = "PENDING"
    KEPT = "KEPT"
    BROKEN = "BROKEN"


class PlaybookRunStatus(StrEnum):
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    HALTED_BY_GUARDRAIL = "HALTED_BY_GUARDRAIL"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class PaymentLinkStatus(StrEnum):
    # Lowercase values, as written in the blueprint (Razorpay's own casing).
    ISSUED = "issued"
    PARTIALLY_PAID = "partially_paid"
    PAID = "paid"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class PaymentMethodAttempted(StrEnum):
    UPI_COLLECT = "UPI_COLLECT"
    UPI_INTENT = "UPI_INTENT"
    CARD = "CARD"
    NETBANKING = "NETBANKING"
    BNPL = "BNPL"
    NONE = "NONE"


class HardStopReason(StrEnum):
    NETWORK_HARD_STOP = "NETWORK_HARD_STOP"
    INSTRUMENT_NOT_RECURRING_CAPABLE = "INSTRUMENT_NOT_RECURRING_CAPABLE"


class ClearingCycleStatus(StrEnum):
    PENDING_CLEARING = "PENDING_CLEARING"
    RETURNED = "RETURNED"
    CLEARED = "CLEARED"


class SystemicScope(StrEnum):
    ISSUER_SPECIFIC = "ISSUER_SPECIFIC"
    NETWORK_WIDE = "NETWORK_WIDE"


class LanguagePref(StrEnum):
    HINGLISH = "HINGLISH"
    ENGLISH = "ENGLISH"


class WhatsAppTemplateCategory(StrEnum):
    """Meta WABA template category (Blueprint Section 3: "utility/marketing").

    `AUTHENTICATION` is a deferred Meta category (OTP/auth templates) — add it
    with an explicit `ALTER TYPE whatsapp_template_category ADD VALUE
    'AUTHENTICATION'` migration only if Torque ever introduces such a use case.

    NOTE: `MerchantWhatsAppTemplate.approval_status` is deliberately NOT an enum
    — Meta owns and evolves that vocabulary. See
    `torque.compliance.whatsapp.WHATSAPP_APPROVED`.
    """

    UTILITY = "UTILITY"
    MARKETING = "MARKETING"


# Enums that back an actual column somewhere in the Milestone 1 schema. Migration
# 0001 creates a Postgres type for every enum in this module; this tuple is the
# subset the 0002-0005 tables reference, kept here as documentation.
MILESTONE_1_COLUMN_ENUMS = (
    LegType,
    CaseStatus,
    MacTier,
    CaseEventType,
    Actor,
    RecoveryType,
    LanguagePref,
)

ALL_ENUMS = (
    LegType,
    MandateType,
    CaseStatus,
    MacTier,
    Network,
    ActionType,
    ActionOutcome,
    BlockReason,
    CaseEventType,
    Actor,
    RecoveryType,
    PromiseStatus,
    PlaybookRunStatus,
    PaymentLinkStatus,
    PaymentMethodAttempted,
    HardStopReason,
    ClearingCycleStatus,
    SystemicScope,
    LanguagePref,
    WhatsAppTemplateCategory,
)
