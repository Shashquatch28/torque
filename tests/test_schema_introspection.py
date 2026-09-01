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
