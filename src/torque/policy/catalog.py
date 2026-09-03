"""The demo-scope playbook catalog — Blueprint §4.1.

"One playbook per non-trivial `root_cause_code`." This module is the single
authoritative source for the eleven catalog playbooks: their identity slug,
`leg_type` / `mandate_type` discriminators, concrete `steps_graph`, and template
`stopping_rules`. `seed_catalog` inserts them **through the ORM** so every graph
passes the same `before_flush` save-time validation (`torque.playbooks`,
Blueprint §4.2) that guards any hand-authored playbook — a catalog graph can no
more be malformed than a merchant's could.

Graphs are deliberately short, structurally-valid outreach/retry ladders. Edge
conditions describe an **action's** delivery outcome, not case recovery (recovery
is detected out-of-band by Module 7 and closes the case regardless of graph
position); the ladder is "the planned sequence of recovery touches, ending when
automation is exhausted." Concrete node/edge shapes are demo-scope — Module 4
owns the *rules for reading* a graph; Module 5 owns executing the actions.

Seeding is an application-level function, NOT an Alembic data migration: the
graphs must clear the ORM guard's validation, which a raw-SQL migration would
bypass (D-085).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.enums import ActionType, LegType, MandateType
from torque.models import Playbook, PlaybookIdentity

# --- playbook identity slugs (Blueprint §4.1) --------------------------------
PLAYBOOK_NSF_RETRY = "PLAYBOOK_NSF_RETRY"
PLAYBOOK_GENERIC_SOFT_RETRY = "PLAYBOOK_GENERIC_SOFT_RETRY"
PLAYBOOK_REQUEST_NEW_INSTRUMENT = "PLAYBOOK_REQUEST_NEW_INSTRUMENT"
PLAYBOOK_SUGGEST_UPI_INTENT = "PLAYBOOK_SUGGEST_UPI_INTENT"
PLAYBOOK_GENERIC_CART_NUDGE = "PLAYBOOK_GENERIC_CART_NUDGE"
PLAYBOOK_SUBSCRIPTION_RETRY_CARD = "PLAYBOOK_SUBSCRIPTION_RETRY_CARD"
PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY = "PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY"
PLAYBOOK_SUBSCRIPTION_RETRY_NACH = "PLAYBOOK_SUBSCRIPTION_RETRY_NACH"
PLAYBOOK_REQUEST_MANDATE_RENEWAL = "PLAYBOOK_REQUEST_MANDATE_RENEWAL"
PLAYBOOK_B2B_LOW_RISK_DUNNING = "PLAYBOOK_B2B_LOW_RISK_DUNNING"
PLAYBOOK_B2B_HIGH_RISK_DUNNING = "PLAYBOOK_B2B_HIGH_RISK_DUNNING"

_FALLBACKS = ("on_no_response", "on_failed", "on_blocked")


def _node(node_id: str, action: ActionType, offset: float, params: dict | None = None) -> dict:
    return {
        "id": node_id,
        "action_template": {"type": action.value},
        "timing_offset_hours": offset,
        "params": params or {},
    }


def _linear_graph(nodes: list[dict]) -> dict:
    """A strictly-forward ladder: every non-terminal node routes to the next node
    on `on_success` and on all three fallbacks; the last node is terminal (no
    outgoing edges). Passes `validate_step_graph` (one on_success + ≥1 fallback
    per non-terminal, no cycles)."""
    edges: list[dict] = []
    for cur, nxt in zip(nodes, nodes[1:], strict=False):
        edges.append({"from": cur["id"], "condition": "on_success", "to": nxt["id"]})
        for cond in _FALLBACKS:
            edges.append({"from": cur["id"], "condition": cond, "to": nxt["id"]})
    return {"entry": nodes[0]["id"], "nodes": nodes, "edges": edges}


def _rules(*, attempts: int, days: int, start: str, end: str, ceiling: int) -> dict:
    return {
        "max_attempts": attempts,
        "max_duration_days": days,
        "allowed_hours": {"start": start, "end": end},
        "escalation_ceiling": ceiling,
    }


@dataclass(frozen=True)
class CatalogEntry:
    playbook_id: str
    leg_type: LegType
    mandate_type: MandateType | None
    steps_graph: dict
    stopping_rules: dict = field(default_factory=dict)


# --- the eleven playbooks (Blueprint §4.1) -----------------------------------

CATALOG: tuple[CatalogEntry, ...] = (
    # Leg 1 — PAYMENT_DEGRADATION
    CatalogEntry(
        PLAYBOOK_NSF_RETRY,
        LegType.PAYMENT_DEGRADATION,
        None,
        _linear_graph(
            [
                _node("retry", ActionType.RETRY_PAYMENT, 0, {"template": "nsf_retry"}),
                _node("nudge", ActionType.SEND_WHATSAPP, 72, {"template": "nsf_nudge"}),
                _node("escalate", ActionType.ESCALATE_HUMAN, 0),
            ]
        ),
        _rules(attempts=3, days=14, start="09:00", end="21:00", ceiling=2),
    ),
    CatalogEntry(
        PLAYBOOK_GENERIC_SOFT_RETRY,
        LegType.PAYMENT_DEGRADATION,
        None,
        _linear_graph(
            [
                _node("retry_1", ActionType.RETRY_PAYMENT, 0, {"template": "soft_retry"}),
                _node("retry_2", ActionType.RETRY_PAYMENT, 48, {"template": "soft_retry"}),
                _node("nudge", ActionType.SEND_WHATSAPP, 24, {"template": "soft_nudge"}),
                _node("escalate", ActionType.ESCALATE_HUMAN, 0),
            ]
        ),
        _rules(attempts=4, days=7, start="09:00", end="21:00", ceiling=2),
    ),
    CatalogEntry(
        PLAYBOOK_REQUEST_NEW_INSTRUMENT,
        LegType.PAYMENT_DEGRADATION,
        None,
        _linear_graph(
            [
                _node(
                    "link", ActionType.GENERATE_PAYMENT_LINK, 0, {"template": "new_instr_link"}
                ),
                _node("wa", ActionType.SEND_WHATSAPP, 0, {"template": "new_instrument_wa"}),
                _node("email", ActionType.SEND_EMAIL, 48, {"template": "new_instrument_email"}),
                _node("escalate", ActionType.ESCALATE_HUMAN, 0),
            ]
        ),
        _rules(attempts=1, days=10, start="09:00", end="20:00", ceiling=1),
    ),
    # Leg 2 — CHECKOUT_ABANDONMENT (gentle nudges; no human escalation)
    CatalogEntry(
        PLAYBOOK_SUGGEST_UPI_INTENT,
        LegType.CHECKOUT_ABANDONMENT,
        None,
        _linear_graph(
            [
                _node("wa", ActionType.SEND_WHATSAPP, 0, {"template": "suggest_upi_intent"}),
                _node("email", ActionType.SEND_EMAIL, 24, {"template": "suggest_upi_intent_email"}),
            ]
        ),
        _rules(attempts=2, days=3, start="09:00", end="21:00", ceiling=1),
    ),
    CatalogEntry(
        PLAYBOOK_GENERIC_CART_NUDGE,
        LegType.CHECKOUT_ABANDONMENT,
        None,
        _linear_graph(
            [
                _node(
                    "wa",
                    ActionType.SEND_WHATSAPP,
                    0,
                    {"template": "cart_nudge", "multi_case_template": "cart_nudge_multi"},
                ),
                _node("email", ActionType.SEND_EMAIL, 24, {"template": "cart_nudge_email"}),
            ]
        ),
        _rules(attempts=2, days=3, start="09:00", end="21:00", ceiling=1),
    ),
    # Leg 3 — SUBSCRIPTION_FAILURE (mandate-type specific)
    CatalogEntry(
        PLAYBOOK_SUBSCRIPTION_RETRY_CARD,
        LegType.SUBSCRIPTION_FAILURE,
        MandateType.CARD,
        _linear_graph(
            [
                _node("retry", ActionType.RETRY_PAYMENT, 0, {"template": "sub_card_retry"}),
                _node("nudge", ActionType.SEND_WHATSAPP, 72, {"template": "sub_card_nudge"}),
                _node("escalate", ActionType.ESCALATE_HUMAN, 0),
            ]
        ),
        _rules(attempts=3, days=14, start="09:00", end="21:00", ceiling=2),
    ),
    CatalogEntry(
        # UPI AutoPay — max_attempts MUST be <= 3 (NPCI, §4.2 hard save-time rule).
        PLAYBOOK_SUBSCRIPTION_RETRY_UPI_AUTOPAY,
        LegType.SUBSCRIPTION_FAILURE,
        MandateType.UPI_AUTOPAY,
        _linear_graph(
            [
                _node(
                    "predebit", ActionType.SEND_PRE_DEBIT_NOTIFICATION, 0, {"template": "upi_pdn"}
                ),
                _node("retry", ActionType.RETRY_PAYMENT, 24, {"template": "sub_upi_retry"}),
                _node("escalate", ActionType.ESCALATE_HUMAN, 0),
            ]
        ),
        _rules(attempts=3, days=14, start="09:00", end="21:00", ceiling=2),
    ),
    CatalogEntry(
        PLAYBOOK_SUBSCRIPTION_RETRY_NACH,
        LegType.SUBSCRIPTION_FAILURE,
        MandateType.NACH,
        _linear_graph(
            [
                _node(
                    "predebit", ActionType.SEND_PRE_DEBIT_NOTIFICATION, 0, {"template": "nach_pdn"}
                ),
                _node("retry", ActionType.RETRY_PAYMENT, 48, {"template": "sub_nach_retry"}),
                _node("escalate", ActionType.ESCALATE_HUMAN, 0),
            ]
        ),
        _rules(attempts=3, days=21, start="09:00", end="20:00", ceiling=2),
    ),
    CatalogEntry(
        PLAYBOOK_REQUEST_MANDATE_RENEWAL,
        LegType.SUBSCRIPTION_FAILURE,
        None,
        _linear_graph(
            [
                _node("wa", ActionType.SEND_WHATSAPP, 0, {"template": "mandate_renewal_wa"}),
                _node("email", ActionType.SEND_EMAIL, 48, {"template": "mandate_renewal_email"}),
                _node("escalate", ActionType.ESCALATE_HUMAN, 0),
            ]
        ),
        _rules(attempts=1, days=10, start="09:00", end="20:00", ceiling=1),
    ),
    # Leg 4 — B2B_RECEIVABLE (dunning; multi_case_template for merged threads)
    CatalogEntry(
        PLAYBOOK_B2B_LOW_RISK_DUNNING,
        LegType.B2B_RECEIVABLE,
        None,
        _linear_graph(
            [
                _node(
                    "email_1",
                    ActionType.SEND_EMAIL,
                    0,
                    {"template": "b2b_gentle", "multi_case_template": "b2b_gentle_multi"},
                ),
                _node("wa", ActionType.SEND_WHATSAPP, 120, {"template": "b2b_gentle_wa"}),
                _node("email_2", ActionType.SEND_EMAIL, 240, {"template": "b2b_gentle_final"}),
            ]
        ),
        _rules(attempts=3, days=30, start="10:00", end="18:00", ceiling=2),
    ),
    CatalogEntry(
        PLAYBOOK_B2B_HIGH_RISK_DUNNING,
        LegType.B2B_RECEIVABLE,
        None,
        _linear_graph(
            [
                _node(
                    "wa",
                    ActionType.SEND_WHATSAPP,
                    0,
                    {"template": "b2b_firm", "multi_case_template": "b2b_firm_multi"},
                ),
                _node("email", ActionType.SEND_EMAIL, 48, {"template": "b2b_firm_email"}),
                _node("escalate", ActionType.ESCALATE_HUMAN, 0),
            ]
        ),
        _rules(attempts=3, days=14, start="09:00", end="19:00", ceiling=1),
    ),
)

CATALOG_BY_ID: dict[str, CatalogEntry] = {e.playbook_id: e for e in CATALOG}


def seed_catalog(session: Session) -> int:
    """Idempotently insert every catalog playbook as version 1, through the ORM
    (so `torque.models.guards` validates each graph + stopping_rules at flush).

    Returns the number of playbook versions newly created. Safe to call repeatedly
    (a re-seed is a no-op) — it never inserts `version + 1`, so it can never mutate
    or fork an existing catalog playbook.
    """
    created = 0
    for entry in CATALOG:
        if session.get(PlaybookIdentity, entry.playbook_id) is None:
            session.add(PlaybookIdentity(playbook_id=entry.playbook_id))
            session.flush()
        exists = session.scalar(
            select(Playbook.version)
            .where(Playbook.playbook_id == entry.playbook_id)
            .where(Playbook.version == 1)
        )
        if exists is not None:
            continue
        session.add(
            Playbook(
                playbook_id=entry.playbook_id,
                version=1,
                leg_type=entry.leg_type,
                mandate_type=entry.mandate_type,
                trigger_condition={},
                steps_graph=entry.steps_graph,
                stopping_rules=entry.stopping_rules,
            )
        )
        session.flush()
        created += 1
    return created
