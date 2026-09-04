"""Module 10 — the Demo Surface control endpoints (Blueprint §10.10 / §10.16).

* `GET  /demo/merchant`          — the demo merchant id + whether it is seeded
* `POST /demo/seed?reset=bool`   — build (or rebuild) the deterministic dataset
* `GET  /demo/scenarios`         — the one-click scenario catalogue (for buttons)
* `POST /demo/inject/{key}`      — run one synthetic scenario against `acc_demo`

All demo endpoints operate only on the fixed demo merchant. `get_db` commits on
a clean return, so a seed / injection persists.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from torque.api.deps import get_db
from torque.demo import DEMO_MERCHANT_ID, DEMO_SCENARIOS, inject_scenario, seed_demo
from torque.demo.seed import DEMO_NOW
from torque.models import Merchant, RevenueLeakCase

router = APIRouter(prefix="/demo", tags=["demo"])


@router.get("/merchant")
def get_demo_merchant(session: Session = Depends(get_db)) -> dict:
    exists = session.get(Merchant, DEMO_MERCHANT_ID) is not None
    seeded = (
        exists
        and session.scalar(
            select(RevenueLeakCase.case_id)
            .where(RevenueLeakCase.merchant_id == DEMO_MERCHANT_ID)
            .limit(1)
        )
        is not None
    )
    return {"merchant_id": DEMO_MERCHANT_ID, "exists": exists, "seeded": seeded}


@router.post("/seed")
def post_seed(
    reset: bool = Query(default=False),
    session: Session = Depends(get_db),
) -> dict:
    return seed_demo(session, now=DEMO_NOW, reset=reset)


@router.get("/scenarios")
def get_scenarios() -> list[dict]:
    return DEMO_SCENARIOS


@router.post("/inject/{key}")
def post_inject(key: str, session: Session = Depends(get_db)) -> dict:
    if session.get(Merchant, DEMO_MERCHANT_ID) is None:
        raise HTTPException(
            status_code=409, detail="demo merchant not seeded — POST /demo/seed first"
        )
    try:
        return inject_scenario(session, key)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
