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
    } <= tables
