"""Phase 6 — the read-only AI HTTP surface: exposes Phase 4's
`explain_case` (a grounded, citation-validated case narrative) to the human
reviewer through the existing Agent Console.

    GET /ai/{merchant_id}/cases/{case_id}/explain
            v
    gather_case_evidence()          (Phase 1, inside explain_case)
            v
    find_precedent()                (Phase 3, inside explain_case)
            v
    provider.structured_generate()  (MockProvider — Phase 4)
            v
    citation validation             (Phase 4's _validate_citations, unmodified)
            v
    CaseNarrative                   (returned verbatim as the response body)

Same conventions as `torque.api.reporting`: one `APIRouter`, `Depends(get_db)`,
a `_require_merchant` guard before anything else. Strictly `GET`, strictly
read-only — this module issues no write of its own and calls nothing outside
`torque.ai`'s own already-read-only, already-tenant-scoped pipeline. It lives
under `torque.api`, not `torque.ai` — `tests/test_ai_boundary.py` only scans
`src/torque/ai/`, so this router is exactly the "future phase" consumer that
boundary was always meant to allow, not an exception to it.

**AI feature flag.** `torque.ai.config.AISettings.enabled` gates exposure
here — the "API-layer concern" `torque.ai.config`'s and `torque.ai.narrative`'s
own docstrings named as Phase 6's job, not invented fresh. Disabled -> `503`
before any database or provider work happens (no merchant/case lookup, no
evidence gathered, no provider called) — the same "not ready" status code
`torque.api.health`'s readiness probe already uses for "infrastructure this
deployment needs is not available right now."

**Provider.** `MockProvider` — the only concrete `LLMProvider` this program
has ever built (Phase 4). `_get_provider` is the single, already-isolated
construction site a future real provider replaces; nothing else in this
module branches on provider identity.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from torque.ai.config import AISettings, get_ai_settings
from torque.ai.exceptions import EvidenceNotFoundError, NarrativeGenerationError
from torque.ai.narrative import explain_case
from torque.ai.providers.base import LLMProvider
from torque.ai.providers.mock_provider import MockProvider
from torque.ai.schemas import CaseNarrative
from torque.api.deps import get_db
from torque.models import Merchant

router = APIRouter(prefix="/ai/{merchant_id}", tags=["ai"])


def _require_merchant(session: Session, merchant_id: str) -> None:
    if session.get(Merchant, merchant_id) is None:
        raise HTTPException(status_code=404, detail=f"unknown merchant {merchant_id!r}")


def _get_provider() -> LLMProvider:
    """The single construction site for the injected `LLMProvider`. Always
    `MockProvider` today — no real, network-backed provider exists yet
    (deferred, D-AI-03). A future phase changes this one function; no
    caller of it changes."""
    return MockProvider()


@router.get("/cases/{case_id}/explain", response_model=CaseNarrative)
async def explain(
    merchant_id: str,
    case_id: uuid.UUID,
    session: Session = Depends(get_db),
    settings: AISettings = Depends(get_ai_settings),
) -> CaseNarrative:
    """Generate a citation-grounded explanation of one case for a human
    reviewer.

    Read-only end to end: `explain_case` (Phase 4) never writes, gathers
    evidence and precedent through the same tenant-scoped, read-only paths
    Phases 1 and 3 already ship, and this handler adds no write, no case
    transition, no `Action`, and no `CaseEvent` of its own.
    """
    if not settings.enabled:
        raise HTTPException(
            status_code=503, detail="AI explanations are not enabled for this deployment"
        )
    _require_merchant(session, merchant_id)
    try:
        return await explain_case(
            session,
            merchant_id=merchant_id,
            case_id=case_id,
            provider=_get_provider(),
        )
    except EvidenceNotFoundError as exc:
        raise HTTPException(status_code=404, detail="case not found for this merchant") from exc
    except NarrativeGenerationError as exc:
        raise HTTPException(
            status_code=502,
            detail="the AI explanation could not be generated for this case",
        ) from exc


__all__ = ["router"]
