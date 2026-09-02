"""Structural invariants that must hold regardless of application logic.

* Raw PII columns (`name`, `phone`, `email`) exist on `counterparty` ONLY.
* No `audit_log_entry` table (eliminated — Section 2.3).
* No `step_history` column anywhere (eliminated — Section 3).
* No `merged_case_ids` column anywhere (replaced by `ActionCase` — Section 3).
* `case_event` has no `updated_at` — an append-only log is never updated.
"""

from __future__ import annotations

from sqlalchemy import inspect


def _all_columns(engine):
    insp = inspect(engine)
    out = {}
    for table in insp.get_table_names():
        out[table] = {c["name"] for c in insp.get_columns(table)}
    return out


def test_pii_columns_live_only_on_counterparty(engine):
    cols = _all_columns(engine)
    for table, names in cols.items():
        for pii in ("name", "phone", "email"):
            if table == "counterparty":
                continue
            assert pii not in names, f"PII column {pii!r} leaked into {table!r}"
    assert {"name", "phone", "email"} <= cols["counterparty"]


def test_no_eliminated_tables(engine):
    tables = set(inspect(engine).get_table_names())
    assert "audit_log_entry" not in tables


def test_no_eliminated_columns(engine):
    for table, names in _all_columns(engine).items():
        assert "step_history" not in names, f"step_history found on {table!r}"
        assert "merged_case_ids" not in names, f"merged_case_ids found on {table!r}"


def test_case_event_is_not_updatable_shape(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("case_event")}
    assert "updated_at" not in cols
    expected = {
        "event_seq_id",
        "case_id",
        "event_type",
        "payload",
        "reasoning",
        "actor",
        "timestamp",
    }
    assert expected <= cols


def test_expected_tables_present(engine):
    tables = set(inspect(engine).get_table_names())
    assert {
        "merchant",
        "counterparty",
        "merchant_counterparty",
        "event",
        "revenue_leak_case",
        "b2b_invoice",
        "case_event",
        # Milestone 2
        "mac_code_registry",
        "card_retry_budget",
        "upi_retry_budget",
        "nach_retry_policy",
        "pre_debit_notification",
        # Milestone 3
        "systemic_event",
        "channel_rate_card",
        # Milestone 4
        "playbook_identity",
        "playbook",
        "merchant_playbook_config",
        "playbook_run",
        # Milestone 5
        "action",
        "action_case",
        # Milestone 6a
        "payment_link",
        "promise_to_pay",
        # Milestone 6b
        "merchant_whatsapp_template",
    } <= tables


# --- Milestone 2 structural invariants -------------------------------------

_TENANT_SCOPED_M2 = (
    "card_retry_budget",
    "upi_retry_budget",
    "nach_retry_policy",
    "pre_debit_notification",
)


def test_m2_retry_tables_are_tenant_scoped(engine):
    cols = _all_columns(engine)
    for table in _TENANT_SCOPED_M2:
        assert "merchant_id" in cols[table], f"{table} must carry merchant_id (decision 1)"


def test_mac_code_registry_is_not_tenant_scoped(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("mac_code_registry")}
    assert "merchant_id" not in cols  # global static config (R3)


def test_upi_retry_budget_has_no_execution_window_column(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("upi_retry_budget")}
    assert "permitted_execution_window" not in cols  # decision 3: constant + predicate


def test_mandate_id_is_not_a_foreign_key(engine):
    """decision 2 - mandate_id is an external identifier String, no DB FK."""
    insp = inspect(engine)
    for table in ("upi_retry_budget", "nach_retry_policy"):
        fk_cols = {c for fk in insp.get_foreign_keys(table) for c in fk["constrained_columns"]}
        assert "mandate_id" not in fk_cols
        col = next(c for c in insp.get_columns(table) if c["name"] == "mandate_id")
        assert col["type"].__class__.__name__ in {"VARCHAR", "String"}


# --- Milestone 3 structural invariants -------------------------------------


def test_m3_systemic_event_is_tenant_scoped(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("systemic_event")}
    assert "merchant_id" in cols  # decision A


def test_channel_rate_card_is_not_tenant_scoped(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("channel_rate_card")}
    assert "merchant_id" not in cols  # global static config (R3 / decision C-D)


def test_revenue_leak_case_systemic_event_id_is_a_real_fk(engine):
    insp = inspect(engine)
    fks = [
        fk
        for fk in insp.get_foreign_keys("revenue_leak_case")
        if fk["constrained_columns"] == ["systemic_event_id"]
    ]
    assert len(fks) == 1
    assert fks[0]["referred_table"] == "systemic_event"
    assert fks[0]["referred_columns"] == ["systemic_event_id"]


# --- Milestone 4 structural invariants -------------------------------------


def test_playbook_tables_are_global(engine):
    for table in ("playbook_identity", "playbook"):
        cols = {c["name"] for c in inspect(engine).get_columns(table)}
        assert "merchant_id" not in cols


def test_playbook_is_append_only_shape(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("playbook")}
    assert "updated_at" not in cols
    assert "created_at" in cols


def test_m4_tenant_scoped_tables(engine):
    for table in ("merchant_playbook_config", "playbook_run"):
        cols = {c["name"] for c in inspect(engine).get_columns(table)}
        assert "merchant_id" in cols


def test_playbook_run_has_no_step_history(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("playbook_run")}
    assert "step_history" not in cols


def test_playbook_run_pins_version_via_composite_fk(engine):
    insp = inspect(engine)
    fks = [
        fk
        for fk in insp.get_foreign_keys("playbook_run")
        if set(fk["constrained_columns"]) == {"playbook_id", "playbook_version"}
    ]
    assert len(fks) == 1
    assert fks[0]["referred_table"] == "playbook"
    assert set(fks[0]["referred_columns"]) == {"playbook_id", "version"}


def test_merchant_playbook_config_playbook_id_is_a_real_fk(engine):
    insp = inspect(engine)
    fks = [
        fk
        for fk in insp.get_foreign_keys("merchant_playbook_config")
        if fk["constrained_columns"] == ["playbook_id"]
    ]
    assert len(fks) == 1
    assert fks[0]["referred_table"] == "playbook_identity"


# --- Milestone 5 structural invariants -------------------------------------


def test_m5_tenant_scoped_tables(engine):
    for table in ("action", "action_case"):
        cols = {c["name"] for c in inspect(engine).get_columns(table)}
        assert "merchant_id" in cols


def test_action_has_no_merged_case_ids(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("action")}
    assert "merged_case_ids" not in cols


def test_action_run_id_is_nullable(engine):
    col = next(c for c in inspect(engine).get_columns("action") if c["name"] == "run_id")
    assert col["nullable"] is True


def test_action_case_composite_pk(engine):
    pk = inspect(engine).get_pk_constraint("action_case")["constrained_columns"]
    assert set(pk) == {"action_id", "case_id"}


def test_case_event_has_no_action_id_column(engine):
    # explicit correlation lives in the payload string only — no column, no FK
    cols = {c["name"] for c in inspect(engine).get_columns("case_event")}
    assert "action_id" not in cols
    fk_tables = {fk["referred_table"] for fk in inspect(engine).get_foreign_keys("case_event")}
    assert "action" not in fk_tables


def test_action_executed_payload_channel_and_cost_nullable():
    from torque.enums import CaseEventType
    from torque.events import validate_payload

    out = validate_payload(
        CaseEventType.ACTION_EXECUTED,
        {
            "action_id": "22222222-2222-2222-2222-222222222222",
            "action_type": "RETRY_PAYMENT",
            "outcome": "SUCCESS",
        },
    )
    assert out["channel"] is None
    assert out["cost"] is None


# --- Milestone 6a structural invariants -----------------------------------


def test_m6a_tenant_scoped_tables(engine):
    for table in ("payment_link", "promise_to_pay"):
        cols = {c["name"] for c in inspect(engine).get_columns(table)}
        assert "merchant_id" in cols


def test_payment_link_action_id_is_nullable_fk(engine):
    insp = inspect(engine)
    col = next(c for c in insp.get_columns("payment_link") if c["name"] == "action_id")
    assert col["nullable"] is True
    fk = next(
        fk for fk in insp.get_foreign_keys("payment_link")
        if fk["constrained_columns"] == ["action_id"]
    )
    assert fk["referred_table"] == "action"


def test_payment_link_has_paid_biconditional_check(engine):
    names = {c["name"] for c in inspect(engine).get_check_constraints("payment_link")}
    assert "ck_payment_link_paid_status_matches_paid_at" in names
    assert "ck_payment_link_amount_paid_non_negative" in names


def test_promise_to_pay_captured_via_is_unique(engine):
    uniques = inspect(engine).get_unique_constraints("promise_to_pay")
    assert any(u["column_names"] == ["captured_via"] for u in uniques)


def test_promise_to_pay_has_no_on_broken_column(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("promise_to_pay")}
    assert "on_broken" not in cols


# --- Milestone 6b structural invariants -----------------------------------


def test_m6b_merchant_whatsapp_template_is_tenant_scoped(engine):
    cols = {c["name"] for c in inspect(engine).get_columns("merchant_whatsapp_template")}
    assert "merchant_id" in cols


def test_m6b_approval_status_is_not_a_pg_enum(engine):
    col = next(
        c
        for c in inspect(engine).get_columns("merchant_whatsapp_template")
        if c["name"] == "approval_status"
    )
    assert col["type"].__class__.__name__ in {"VARCHAR", "String"}
    assert getattr(col["type"], "name", None) != "whatsapp_approval_status"


def test_m6b_no_uniqueness_beyond_pk(engine):
    assert inspect(engine).get_unique_constraints("merchant_whatsapp_template") == []
    pk = inspect(engine).get_pk_constraint("merchant_whatsapp_template")
    assert pk["constrained_columns"] == ["template_id"]


def test_m6b_gate_index_present_and_exact(engine):
    idx = {
        i["name"]: i["column_names"]
        for i in inspect(engine).get_indexes("merchant_whatsapp_template")
    }
    assert idx["ix_merchant_whatsapp_template_gate"] == [
        "merchant_id",
        "leg_type",
        "category",
    ]


# --- Milestone 7a structural invariants ----------------------------------


def test_m7a_event_ingestion_index_present_and_exact(engine):
    idx = {i["name"]: i["column_names"] for i in inspect(engine).get_indexes("event")}
    # migration 0013 — the trailing-window lookup Module 2 §2.4/§2.5 needs.
    assert idx["ix_event_merchant_type_received_at"] == [
        "merchant_id",
        "type",
        "received_at",
    ]


def test_m7a_event_idempotency_uniqueness_unchanged(engine):
    # M7a adds an HTTP endpoint and one index — no new table, and the
    # idempotency contract is still the single UNIQUE(idempotency_key).
    uqs = inspect(engine).get_unique_constraints("event")
    assert [u["column_names"] for u in uqs] == [["idempotency_key"]]


# --- Milestone 7b structural invariants ----------------------------------


def test_m7b_is_logic_only_no_schema_change(engine):
    # M7b is pure ingestion logic (Celery buffer + dedup + Leg-1 case creation).
    # It adds no table, no enum, no migration.
    tables = set(inspect(engine).get_table_names())
    assert {"revenue_leak_case", "card_retry_budget", "counterparty", "event"} <= tables
    assert not {
        "scheduled_jobs",
        "buffered_event",
        "checkout_session",
        "celery_taskmeta",
    } & tables


def test_m7b_payment_degradation_context_allows_unset_hard_decline():
    # Ingestion must be able to write is_hard_decline=None (Module 3 owns the
    # hard/soft verdict). Also carries the merged abandonment context.
    from torque.contexts import validate_context
    from torque.enums import LegType

    out = validate_context(LegType.PAYMENT_DEGRADATION, {"gateway": "razorpay"})
    assert out["is_hard_decline"] is None
    assert out["merged_abandonment_context"] is None


# --- Milestone 7c structural invariants ---------------------------------


def test_m7c_is_logic_only_no_schema_change(engine):
    # Systemic detection (§2.5, NETWORK_WIDE) is pure ingestion logic + one
    # state-machine edge. It adds no table, no enum, no CaseEventType, no
    # migration.
    tables = set(inspect(engine).get_table_names())
    assert {"systemic_event", "revenue_leak_case", "event", "case_event"} <= tables
    assert not {"systemic_baseline", "systemic_window", "celerybeat"} & tables

    from torque.enums import CaseEventType

    assert len(list(CaseEventType)) == 10  # no SYSTEMIC_HOLD_RESOLVED added


def test_m7c_state_machine_has_exactly_the_approved_edge():
    from torque.enums import CaseStatus
    from torque.state_machine import _TRANSITIONS

    assert CaseStatus.SYSTEMIC_HOLD in _TRANSITIONS[CaseStatus.PLAYBOOK_ACTIVE]
    assert _TRANSITIONS[CaseStatus.SYSTEMIC_HOLD] == {CaseStatus.DIAGNOSING}
    # the withheld edges are still withheld
    assert CaseStatus.SYSTEMIC_HOLD not in _TRANSITIONS[CaseStatus.DIAGNOSING]
    assert CaseStatus.CANCELLED not in _TRANSITIONS[CaseStatus.DETECTED]
