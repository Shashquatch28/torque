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


# --- Milestone 4 playbook fixtures ---------------------------------------

VALID_STEPS_GRAPH = {
    "entry": "n1",
    "nodes": [
        {
            "id": "n1",
            "action_template": {"type": "SEND_WHATSAPP"},
            "timing_offset_hours": 0,
            "params": {},
        },
        {
            "id": "n2",
            "action_template": {"type": "ESCALATE_HUMAN"},
            "timing_offset_hours": 24,
            "params": {},
        },
    ],
    "edges": [
        {"from": "n1", "condition": "on_success", "to": "n2"},
        {"from": "n1", "condition": "on_failed", "to": "n2"},
    ],
}

VALID_STOPPING_RULES = {
    "max_attempts": 3,
    "max_duration_days": 7,
    "allowed_hours": {"start": "08:00", "end": "19:00"},
    "escalation_ceiling": 2,
}


@pytest.fixture()
def make_playbook(db):
    """Create (or reuse) a `playbook_identity` row and insert one `playbook`
    version. Returns the `Playbook` instance."""
    from copy import deepcopy

    from torque.enums import LegType
    from torque.models import Playbook, PlaybookIdentity

    seq = {"n": 0}

    def _make(**kw):
        seq["n"] += 1
        playbook_id = kw.pop("playbook_id", f"pb_test_{seq['n']}")
        version = kw.pop("version", 1)
        if db.get(PlaybookIdentity, playbook_id) is None:
            db.add(PlaybookIdentity(playbook_id=playbook_id))
            db.flush()
        pb = Playbook(
            playbook_id=playbook_id,
            version=version,
            leg_type=kw.pop("leg_type", LegType.PAYMENT_DEGRADATION),
            mandate_type=kw.pop("mandate_type", None),
            trigger_condition=kw.pop("trigger_condition", {}),
            steps_graph=kw.pop("steps_graph", deepcopy(VALID_STEPS_GRAPH)),
            stopping_rules=kw.pop("stopping_rules", deepcopy(VALID_STOPPING_RULES)),
            **kw,
        )
        db.add(pb)
        db.flush()
        return pb

    return _make


@pytest.fixture()
def make_playbook_run(db, make_case, make_playbook):
    from torque.models import PlaybookRun

    def _make(*, case=None, playbook=None, **kw):
        pb = playbook or make_playbook()
        c = case or make_case()
        run = PlaybookRun(
            merchant_id=c.merchant_id,
            case_id=c.case_id,
            playbook_id=pb.playbook_id,
            playbook_version=pb.version,
            **kw,
        )
        db.add(run)
        db.flush()
        return run

    return _make


@pytest.fixture()
def make_action(db, make_case):
    from datetime import UTC, datetime

    from torque.enums import ActionOutcome, ActionType, Actor, BlockReason
    from torque.events import write_action_and_event
    from torque.models import Action

    def _make(
        *,
        case=None,
        run=None,
        outcome=ActionOutcome.SUCCESS,
        action_type=ActionType.SEND_WHATSAPP,
        channel="whatsapp",
        block_reason=None,
        cost=None,
        attributions=None,
        content_sent=None,
    ):
        c = case or make_case()
        blocked = ActionOutcome(outcome) is ActionOutcome.BLOCKED_BY_GUARDRAIL
        action = Action(
            merchant_id=c.merchant_id,
            primary_case_id=c.case_id,
            run_id=(run.run_id if run is not None else None),
            action_type=action_type,
            channel=channel,
            content_sent=content_sent,
            executed_at=None if blocked else datetime.now(UTC),
            outcome=outcome,
            block_reason=(block_reason or BlockReason.QUIET_HOURS) if blocked else None,
            cost=cost,
        )
        write_action_and_event(
            db, action=action, actor=Actor.SYSTEM, attributions=attributions
        )
        return action

    return _make


@pytest.fixture()
def make_payment_link(db, make_case, make_action):
    from decimal import Decimal

    from torque.enums import PaymentLinkStatus
    from torque.models import PaymentLink

    seq = {"n": 0}

    def _make(*, case=None, action="default", **kw):
        seq["n"] += 1
        c = case or make_case()
        if action == "default":
            act = make_action(case=c)
        else:
            act = action  # None -> unattributed link, or an explicit Action
        link = PaymentLink(
            link_id=kw.pop("link_id", f"plink_test_{seq['n']}"),
            merchant_id=c.merchant_id,
            action_id=(act.action_id if act is not None else None),
            case_id=c.case_id,
            status=kw.pop("status", PaymentLinkStatus.ISSUED),
            amount_paid=kw.pop("amount_paid", Decimal("0")),
            **kw,
        )
        db.add(link)
        db.flush()
        return link

    return _make


@pytest.fixture()
def make_promise(db, make_case, make_action):
    from datetime import date
    from decimal import Decimal

    from torque.enums import PromiseStatus
    from torque.models import PromiseToPay

    def _make(*, case=None, action=None, **kw):
        c = case or make_case()
        act = action or make_action(case=c)
        promise = PromiseToPay(
            merchant_id=c.merchant_id,
            case_id=c.case_id,
            captured_via=act.action_id,
            promised_amount=kw.pop("promised_amount", Decimal("1000.00")),
            promised_date=kw.pop("promised_date", date(2026, 10, 1)),
            status=kw.pop("status", PromiseStatus.PENDING),
            **kw,
        )
        db.add(promise)
        db.flush()
        return promise

    return _make


@pytest.fixture()
def make_wa_template(db, make_merchant):
    from torque.enums import LegType, WhatsAppTemplateCategory
    from torque.models import MerchantWhatsAppTemplate

    seq = {"n": 0}

    def _make(
        *,
        merchant=None,
        leg_type=LegType.PAYMENT_DEGRADATION,
        category=WhatsAppTemplateCategory.UTILITY,
        approval_status="APPROVED",
        template_name="nudge_tmpl",
        **kw,
    ):
        seq["n"] += 1
        m = merchant or make_merchant()
        tmpl = MerchantWhatsAppTemplate(
            template_id=kw.pop("template_id", f"wamtpl_test_{seq['n']}"),
            merchant_id=m.merchant_id,
            template_name=template_name,
            category=category,
            approval_status=approval_status,
            leg_type=leg_type,
            **kw,
        )
        db.add(tmpl)
        db.flush()
        return tmpl

    return _make
