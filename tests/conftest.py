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

import json
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


# --- Milestone 7a: Razorpay webhook HTTP harness -------------------------

# Fixed secrets for the test deployment. The webhook endpoint verifies against
# exactly one of these depending on the deployment's configured mode.
WEBHOOK_TEST_SECRET = "whsec_torque_test_9f3a"
WEBHOOK_LIVE_SECRET = "whsec_torque_live_1c74"
# Dedicated secret for the §2.6 signed synthetic `checkout.abandoned` endpoint.
CHECKOUT_INJECTION_SECRET = "chsec_torque_inject_5b2e"


def razorpay_payment_body(
    *,
    event: str = "payment.failed",
    payment_id: str = "pay_M7B001",
    order_id: str | None = "order_M7B001",
    amount_paise: int = 49900,
    method: str = "card",
    email: str | None = "buyer@example.com",
    contact: str | None = "+919810000001",
    token_id: str | None = "token_M7B001",
    card_id: str | None = None,
    error_code: str | None = "BAD_REQUEST_ERROR",
) -> bytes:
    """A Razorpay `payment.failed` / `payment.captured` webhook body (the parts
    M7b reads). Returns raw bytes ready to sign."""
    entity: dict = {"id": payment_id, "amount": amount_paise, "currency": "INR"}
    if order_id is not None:
        entity["order_id"] = order_id
    if method is not None:
        entity["method"] = method
    if email is not None:
        entity["email"] = email
    if contact is not None:
        entity["contact"] = contact
    if token_id is not None:
        entity["token_id"] = token_id
    if card_id is not None:
        entity["card_id"] = card_id
    if error_code is not None:
        entity["error_code"] = error_code
    body = {
        "entity": "event",
        "account_id": "acc_RZP",
        "event": event,
        "contains": ["payment"],
        "payload": {"payment": {"entity": entity}},
        "created_at": 1_760_000_000,
    }
    return json.dumps(body).encode()


def razorpay_subscription_body(
    *,
    event: str = "subscription.charged.failed",
    subscription_id: str = "sub_M8001",
    payment_id: str = "pay_M8001",
    amount_paise: int = 49900,
    method: str = "upi",
    token_id: str | None = "token_M8001",
    paid_count: int = 4,
    email: str | None = "subscriber@example.com",
    contact: str | None = "+919810000900",
    error_code: str | None = "BAD_REQUEST_ERROR",
) -> bytes:
    """A Razorpay `subscription.charged.failed` / `subscription.charged` webhook
    body — carries both a `payment` entity and a `subscription` entity."""
    pay: dict = {"id": payment_id, "amount": amount_paise, "currency": "INR"}
    if method is not None:
        pay["method"] = method
    if token_id is not None:
        pay["token_id"] = token_id
    if email is not None:
        pay["email"] = email
    if contact is not None:
        pay["contact"] = contact
    if error_code is not None:
        pay["error_code"] = error_code
    sub: dict = {"id": subscription_id, "paid_count": paid_count, "status": "active"}
    body = {
        "entity": "event",
        "account_id": "acc_RZP",
        "event": event,
        "contains": ["payment", "subscription"],
        "payload": {"payment": {"entity": pay}, "subscription": {"entity": sub}},
        "created_at": 1_760_000_000,
    }
    return json.dumps(body).encode()


def checkout_abandoned_body(
    *,
    cart_id: str = "cart_M2001",
    cart_value_paise: int = 49900,
    drop_stage: str = "vpa_entry",
    payment_method_attempted: str = "UPI_COLLECT",
    contact: str | None = "+919810002001",
    email: str | None = "shopper@example.com",
) -> bytes:
    """A synthetic `checkout.abandoned` injection body (Leg 2, §2.6)."""
    entity: dict = {
        "cart_id": cart_id,
        "cart_value": cart_value_paise,
        "drop_stage": drop_stage,
        "payment_method_attempted": payment_method_attempted,
    }
    if contact is not None:
        entity["contact"] = contact
    if email is not None:
        entity["email"] = email
    body = {
        "event": "checkout.abandoned",
        "payload": {"checkout": {"entity": entity}},
        "created_at": 1_760_000_000,
    }
    return json.dumps(body).encode()


def razorpay_invoice_body(
    *,
    invoice_id: str = "inv_M2001",
    amount_paise: int = 100_000,
    amount_paid_paise: int = 0,
    amount_due_paise: int | None = None,
    expire_by: int | None = 1_760_000_000,
    contact: str | None = "+919810004001",
    email: str | None = "ap@acme-corp.test",
    terms: str | None = "NET30",
    gst: bool = True,
) -> bytes:
    """A Razorpay `invoice.overdue` webhook body (Leg 4)."""
    entity: dict = {
        "id": invoice_id,
        "amount": amount_paise,
        "amount_paid": amount_paid_paise,
        "currency": "INR",
        "status": "issued",
    }
    if amount_due_paise is not None:
        entity["amount_due"] = amount_due_paise
    if expire_by is not None:
        entity["expire_by"] = expire_by
    if terms is not None:
        entity["terms"] = terms
    if gst:
        entity["gst"] = {"gstin": "27AAAAA0000A1Z5"}
    cd: dict = {}
    if contact is not None:
        cd["contact"] = contact
    if email is not None:
        cd["email"] = email
    if cd:
        entity["customer_details"] = cd
    body = {
        "entity": "event",
        "account_id": "acc_RZP",
        "event": "invoice.overdue",
        "contains": ["invoice"],
        "payload": {"invoice": {"entity": entity}},
        "created_at": 1_760_000_000,
    }
    return json.dumps(body).encode()


@pytest.fixture()
def make_api_client(db, monkeypatch):
    """Factory for a `TestClient` over the ingestion app, wired to the test
    session (same rolled-back transaction the test asserts against) and a
    `Settings` with known webhook secrets. `mode` picks which secret the
    endpoint verifies against ("test" | "live").

    By default both ingestion buffer tasks' `apply_async` are replaced with spies
    (`client.buffer_enqueue` for `payment.failed`, `client.subscription_enqueue`
    for `subscription.charged.failed`, both `MagicMock`s) so tests never touch a
    real broker; pass `patch_enqueue=False` to let a real (e.g. eager) enqueue
    happen.
    """
    from unittest.mock import MagicMock

    from fastapi.testclient import TestClient

    from torque.api.app import create_app
    from torque.api.deps import get_db
    from torque.config import Settings, get_settings

    created: list[TestClient] = []

    def _make(mode: str = "test", *, with_secrets: bool = True, patch_enqueue: bool = True):
        spy = MagicMock(name="resolve_buffered_event_task.apply_async")
        sub_spy = MagicMock(name="resolve_subscription_buffered_event_task.apply_async")
        checkout_spy = MagicMock(name="create_checkout_case_task.apply_async")
        invoice_spy = MagicMock(name="ingest_invoice_task.apply_async")
        if patch_enqueue:
            monkeypatch.setattr(
                "torque.ingestion.tasks.resolve_buffered_event_task.apply_async", spy
            )
            monkeypatch.setattr(
                "torque.ingestion.tasks.resolve_subscription_buffered_event_task.apply_async",
                sub_spy,
            )
            monkeypatch.setattr(
                "torque.ingestion.tasks.create_checkout_case_task.apply_async", checkout_spy
            )
            monkeypatch.setattr(
                "torque.ingestion.tasks.ingest_invoice_task.apply_async", invoice_spy
            )
        settings = Settings(
            razorpay_webhook_secret_test=WEBHOOK_TEST_SECRET if with_secrets else None,
            razorpay_webhook_secret_live=WEBHOOK_LIVE_SECRET if with_secrets else None,
            razorpay_webhook_mode=mode,
            checkout_injection_secret=CHECKOUT_INJECTION_SECRET if with_secrets else None,
        )
        app = create_app()
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_settings] = lambda: settings
        client = TestClient(app)
        client.buffer_enqueue = spy
        client.subscription_enqueue = sub_spy
        client.checkout_enqueue = checkout_spy
        client.invoice_enqueue = invoice_spy
        created.append(client)
        return client

    yield _make
    for client in created:
        client.close()


@pytest.fixture()
def api_client(make_api_client):
    """A `TestClient` in test-mode (verifies against `WEBHOOK_TEST_SECRET`)."""
    return make_api_client()


@pytest.fixture()
def celery_eager():
    """Run Celery tasks inline (no broker, no worker) for the duration of a
    test. Restores the app config afterwards."""
    from torque.ingestion.celery_app import celery_app

    prev_eager = celery_app.conf.task_always_eager
    prev_prop = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        yield celery_app
    finally:
        celery_app.conf.task_always_eager = prev_eager
        celery_app.conf.task_eager_propagates = prev_prop


# --- Milestone 7c: systemic-detection harness ---------------------------


@pytest.fixture()
def systemic_policy(monkeypatch):
    """Bind `torque.ingestion.systemic.get_policy` to a `PolicyConfig` with
    test-friendly systemic knobs (the production defaults would need ~10k
    baseline rows to reach `systemic_baseline_floor_per_min`). Returns a setter
    so each test dials only what it needs; unspecified knobs keep the defaults
    below."""
    from torque.config import PolicyConfig

    def _set(**overrides):
        cfg = dict(
            systemic_detection_window_minutes=10,
            systemic_baseline_days=1,
            systemic_spike_multiplier=5.0,
            systemic_baseline_floor_per_min=0.01,
            systemic_absolute_count_floor=5,
            systemic_sustain_window_minutes=10,
        )
        cfg.update(overrides)
        policy = PolicyConfig(**cfg)
        monkeypatch.setattr("torque.ingestion.systemic.get_policy", lambda: policy)
        return policy

    return _set


@pytest.fixture()
def make_failure_events(db):
    """Insert `count` `payment.failed` `Event` rows for `merchant`, spread evenly
    across `[now - start_minutes_ago, now - end_minutes_ago)`."""
    from datetime import UTC, datetime, timedelta

    from torque.models import Event

    seq = {"n": 0}

    def _make(merchant, *, count, start_minutes_ago, end_minutes_ago=0.0):
        now = datetime.now(UTC)
        span = start_minutes_ago - end_minutes_ago
        rows = []
        for i in range(count):
            seq["n"] += 1
            frac = (i + 0.5) / count if count else 0.0
            offset = start_minutes_ago - frac * span
            ev = Event(
                merchant_id=merchant.merchant_id,
                type="payment.failed",
                idempotency_key=f"evt_sysfail_{seq['n']}",
                raw_payload={"event": "payment.failed"},
                received_at=now - timedelta(minutes=offset),
            )
            db.add(ev)
            rows.append(ev)
        db.flush()
        return rows

    return _make


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


# --- Module 5 execution fixtures -----------------------------------------


@pytest.fixture()
def seeded_catalog(db):
    """The Module 4 playbook catalog, seeded through the ORM (validated graphs)."""
    from torque.policy.catalog import seed_catalog

    seed_catalog(db)


@pytest.fixture()
def make_active_run(db, seeded_catalog, make_merchant, make_counterparty, make_event):
    """Create a diagnosed `PLAYBOOK_ACTIVE` case, run Module 4 `activate_case` to
    instantiate its version-pinned run, and arm the Module 5 timer. Returns
    `(case, run, job)`. `payday=False` (default) writes
    `payday_cycle_override_enabled=False` so retry steps fire on their static
    offset rather than a month-end target."""
    from torque.enums import CaseStatus, LegType
    from torque.execution import schedule_run
    from torque.models import RevenueLeakCase
    from torque.policy.engine import ActivationOutcome, activate_case

    def _make(
        *,
        leg=LegType.PAYMENT_DEGRADATION,
        root_cause_code,
        context=None,
        merchant=None,
        counterparty=None,
        amount_at_risk=1000,
        suggested_timing_adjustment=None,
        payday=False,
    ):
        m = merchant or make_merchant(
            risk_appetite_config={"payday_cycle_override_enabled": payday}
        )
        cp = counterparty or make_counterparty()
        ev = make_event(m)
        default_ctx = {} if leg is LegType.B2B_RECEIVABLE else {"gateway": "razorpay"}
        case = RevenueLeakCase(
            merchant_id=m.merchant_id,
            leg_type=leg,
            source_event_id=ev.event_id,
            counterparty_id=cp.counterparty_id,
            amount_at_risk=amount_at_risk,
            context=context if context is not None else default_ctx,
            status=CaseStatus.PLAYBOOK_ACTIVE,
            root_cause_code=root_cause_code,
            suggested_timing_adjustment=suggested_timing_adjustment,
        )
        db.add(case)
        db.flush()
        outcome = activate_case(db, case_id=case.case_id)
        assert outcome is ActivationOutcome.RUN_CREATED, outcome
        from sqlalchemy import select as _select

        from torque.models import PlaybookRun

        run = db.scalars(
            _select(PlaybookRun).where(PlaybookRun.case_id == case.case_id)
        ).one()
        job = schedule_run(db, run_id=run.run_id)
        return case, run, job

    return _make


@pytest.fixture()
def drain_run(db):
    """Execute a run's scheduled steps to completion, advancing a virtual clock to
    each step's `fire_at` (always in-window by construction). Returns the list of
    `StepResult`s."""
    from sqlalchemy import select as _select

    from torque.execution import execute_due_jobs
    from torque.models import PlaybookRun, ScheduledJob

    def _drain(run, *, legs=None, max_iter=25):
        from torque.enums import LegType

        legs = legs or tuple(LegType)
        results = []
        for _ in range(max_iter):
            job = db.scalars(
                _select(ScheduledJob).where(ScheduledJob.run_id == run.run_id)
            ).first()
            if job is None:
                break
            results.extend(execute_due_jobs(db, leg_types=legs, now=job.fire_at))
            db.refresh(run) if db.get(PlaybookRun, run.run_id) else None
        return results

    return _drain


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
