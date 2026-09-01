"""`alembic upgrade head` then `downgrade base` then `upgrade head` on a fresh,
isolated database. Named `zz` so it sorts last; it uses its own database so it
never disturbs the main suite's schema.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

from tests.conftest import REPO_ROOT, TEST_DATABASE_URL, _admin_url

# render_as_string(hide_password=False): plain str(URL) masks the password as "***".
ROUNDTRIP_URL = make_url(TEST_DATABASE_URL).set(database="torque_roundtrip").render_as_string(
    hide_password=False
)
EXPECTED_TABLES = {
    "merchant",
    "counterparty",
    "merchant_counterparty",
    "event",
    "revenue_leak_case",
    "b2b_invoice",
    "case_event",
}


def _alembic(url: str, direction: str, rev: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    os.environ["TORQUE_ALEMBIC_URL"] = url
    getattr(command, direction)(cfg, rev)


@pytest.fixture()
def roundtrip_db():
    admin = create_engine(_admin_url(TEST_DATABASE_URL), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text('DROP DATABASE IF EXISTS "torque_roundtrip"'))
            conn.execute(text('CREATE DATABASE "torque_roundtrip"'))
    except OperationalError as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL not reachable: {exc.orig}")
    finally:
        admin.dispose()
    try:
        yield ROUNDTRIP_URL
    finally:
        os.environ["TORQUE_ALEMBIC_URL"] = TEST_DATABASE_URL
        admin = create_engine(_admin_url(TEST_DATABASE_URL), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text('DROP DATABASE IF EXISTS "torque_roundtrip"'))
        admin.dispose()


def test_upgrade_downgrade_upgrade(roundtrip_db):
    url = roundtrip_db
    eng = create_engine(url)

    _alembic(url, "upgrade", "head")
    assert EXPECTED_TABLES <= set(inspect(eng).get_table_names())

    _alembic(url, "downgrade", "base")
    remaining = set(inspect(eng).get_table_names())
    assert not (EXPECTED_TABLES & remaining)
    # enum types are also dropped on downgrade to base
    with eng.connect() as conn:
        n_enums = conn.execute(
            text("SELECT count(*) FROM pg_type WHERE typtype = 'e'")
        ).scalar()
    assert n_enums == 0

    _alembic(url, "upgrade", "head")
    assert EXPECTED_TABLES <= set(inspect(eng).get_table_names())
    eng.dispose()
