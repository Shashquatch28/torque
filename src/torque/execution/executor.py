"""The action-executor abstraction — Blueprint §5.4 (demo-scope stubs).

`run_action` is the single seam where a real channel adapter attaches later
(WhatsApp → Meta Cloud API, Email → Resend, SMS → Fast2SMS, Payment Link →
Razorpay Payment Links, Retry → Razorpay Payments/Mandate-Execute/NACH
re-presentment — §5.4). In demo scope it performs **no external I/O**: it returns
a deterministic `ActionOutcome` so the whole execution loop is exercisable in the
test harness without a network.

`run_action` is module-level indirection on purpose — tests monkeypatch it to
force `FAILED` / `NO_RESPONSE` and exercise the graph's fallback edges. The
default returns `SUCCESS` for every action type (a delivered message / an accepted
retry submission). Note "retry submitted successfully" is NOT "payment recovered":
recovery is a reconciliation signal (Module 7), out-of-band from this loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from torque.enums import ActionOutcome, ActionType


@dataclass(frozen=True)
class ActionContext:
    """What an executor needs to perform one action. Rendering (single vs
    `multi_case_template`) is resolved by the caller (`torque.policy.traversal`
    + the runner); the executor receives the already-chosen template + channel."""

    action_type: ActionType
    channel: str | None
    template: str | None
    content: str | None = None


# Which channel string each contact/link action reports on its Action row. Retry
# and escalation carry no messaging channel.
_CHANNEL: dict[ActionType, str | None] = {
    ActionType.SEND_WHATSAPP: "whatsapp",
    ActionType.SEND_EMAIL: "email",
    ActionType.SEND_SMS: "sms",
    ActionType.SEND_PRE_DEBIT_NOTIFICATION: "whatsapp",
    ActionType.GENERATE_PAYMENT_LINK: "payment_link",
    ActionType.RETRY_PAYMENT: None,
    ActionType.ESCALATE_HUMAN: None,
    ActionType.LOG_PROMISE: None,
    ActionType.SYSTEMIC_HOLD: None,
}


def channel_for(action_type: ActionType) -> str | None:
    return _CHANNEL.get(ActionType(action_type))


def run_action(context: ActionContext) -> ActionOutcome:
    """Execute one action and return its outcome. Demo stub — no external call.

    Monkeypatch this in tests to drive `FAILED` / `NO_RESPONSE` fallback paths.
    """
    return ActionOutcome.SUCCESS
