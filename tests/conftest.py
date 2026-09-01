"""Test harness.

Requires a reachable PostgreSQL server. The suite:

1. connects to an admin database and (re)creates a throwaway schema in the test
   database (`DROP SCHEMA public CASCADE; CREATE SCHEMA public`);
2. runs `alembic upgrade head` against it — so every test also exercises the
   migrations;
3. hands each test a `db` session joined to an outer transaction that is rolled
   back afterwards, for isolation and speed.

If no server is reachable the whole suite is skipped with an explanatory
message (never a spurious failure).

Connection settings (env, with sensible localhost defaults):
* TEST_DATABASE_URL     — the test database
* TORQUE_TEST_ADMIN_URL — a database to issue CREATE DATABASE from
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

REPO_ROOT = Path(__file__).resolve().parent.parent

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://postgres:postgres@localhost:5442/torque_test",
)


def _admin_url(test_url: str) -> str:
    if os.environ.get("TORQUE_TEST_ADMIN_URL"):
        return os.environ["TORQUE_TEST_ADMIN_URL"]
    parts = urlsplit(test_url)
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))


def _reset_test_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    db_name = url.database
    admin = create_engine(_admin_url(TEST_DATABASE_URL), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": db_name}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    admin.dispose()

    scratch = create_engine(TEST_DATABASE_URL, isolation_level="AUTOCOMMIT")
    with scratch.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    scratch.dispose()


def _alembic_upgrade_head() -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    os.environ["TORQUE_ALEMBIC_URL"] = TEST_DATABASE_URL
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
def _database():
    try:
        _reset_test_database()
    except OperationalError as exc:  # pragma: no cover - environment-dependent
        pytest.skip(
            "PostgreSQL is not reachable for the test suite "
            f"({TEST_DATABASE_URL!r}): {exc.orig}. "
            "Start it with `docker compose up -d db` or set TEST_DATABASE_URL."
        )
    _alembic_upgrade_head()
    yield


@pytest.fixture(scope="session")
def engine(_database):
    eng = create_engine(TEST_DATABASE_URL, future=True)
    yield eng
    eng.dispose()


@pytest.fixture()
def db(engine):
    """A guarded session joined to an outer transaction, rolled back after."""
    from torque.db.session import SessionLocal

    connection = engine.connect()
    outer = connection.begin()
    session = SessionLocal(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        connection.close()


# --- lightweight factories -------------------------------------------------


@pytest.fixture()
def make_merchant(db):
    from torque.models import Merchant

    seq = {"n": 0}

    def _make(**kw):
        seq["n"] += 1
        m = Merchant(
            merchant_id=kw.pop("merchant_id", f"acc_test_{seq['n']}"),
            business_type=kw.pop("business_type", "D2C"),
            tier=kw.pop("tier", "Metro"),
            channels_enabled=kw.pop("channels_enabled", ["whatsapp", "email"]),
            risk_appetite_config=kw.pop("risk_appetite_config", {}),
            **kw,
        )
        db.add(m)
        db.flush()
        return m

    return _make


@pytest.fixture()
def make_counterparty(db):
    from torque.models import Counterparty

    def _make(**kw):
        cp = Counterparty(
            name=kw.pop("name", "Test Person"),
            phone=kw.pop("phone", "+919000000000"),
            email=kw.pop("email", "test@example.com"),
            payment_failure_nudge_consent=kw.pop("payment_failure_nudge_consent", True),
            **kw,
        )
        db.add(cp)
        db.flush()
        return cp

    return _make


@pytest.fixture()
def make_event(db):
    from torque.models import Event

    seq = {"n": 0}

    def _make(merchant, **kw):
        seq["n"] += 1
        ev = Event(
            merchant_id=merchant.merchant_id,
            type=kw.pop("type", "payment.failed"),
            idempotency_key=kw.pop("idempotency_key", f"evt_test_{seq['n']}"),
            raw_payload=kw.pop("raw_payload", {"stub": True}),
            **kw,
        )
        db.add(ev)
        db.flush()
        return ev

    return _make


@pytest.fixture()
def make_case(db, make_merchant, make_counterparty, make_event):
    from torque.enums import LegType
    from torque.models import RevenueLeakCase

    def _make(*, merchant=None, counterparty=None, leg=LegType.PAYMENT_DEGRADATION, **kw):
        m = merchant or make_merchant()
        cp = counterparty or make_counterparty()
        ev = make_event(m)
        default_ctx = {} if leg is LegType.B2B_RECEIVABLE else {"gateway": "razorpay"}
        case = RevenueLeakCase(
            merchant_id=m.merchant_id,
            leg_type=leg,
            source_event_id=ev.event_id,
            counterparty_id=cp.counterparty_id,
            amount_at_risk=kw.pop("amount_at_risk", 1000),
            context=kw.pop("context", default_ctx),
            **kw,
        )
        db.add(case)
        db.flush()
        return case

    return _make
