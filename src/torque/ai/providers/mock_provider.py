"""`MockProvider` — the required, network-independent `LLMProvider`.

The standard AI test suite injects this provider exclusively. It makes ZERO
network calls, needs no API key, and is fully deterministic: the same
`(system, user)` input always produces the same output. Unlike a
hard-coded, evidence-disconnected stub, it actually PARSES the `<evidence>`
JSON block out of the `user` message (the same message a real provider
would receive) and builds a genuinely evidence-grounded `CaseNarrative` from
it — every claim it emits cites a real `reference_id`/`evidence_id` present
in that payload, so tests can meaningfully assert "the citation ids
correspond to the supplied evidence," not just "the shape is valid."

It also supports a handful of constructor flags to deliberately simulate
every provider failure mode Phase 4's degradation behavior must handle:
an outright exception, schema-invalid output, a non-`BaseModel` return
value, a fabricated citation, and a wrong self-reported `case_id` (to prove
`torque.ai.narrative.explain_case` never trusts it). None of these flags
are used by the "happy path" tests, and none require network access either.

**Phase 8 addition: `delay_seconds`.** Simulates a slow/hanging provider —
needed to test `torque.ai.narrative.explain_case`'s Phase 8 hardening
(`asyncio.wait_for`-enforced `timeout_s`) without a real network-backed
provider. Same convention as every other flag here: off by default, opted
into only by the specific test that needs it.
"""

from __future__ import annotations

import asyncio
import json

from pydantic import BaseModel

from torque.ai.providers.base import LLMProvider
from torque.ai.schemas import NO_PRECEDENT_NOTE

_DEFAULT_PROVIDER_ID = "mock:deterministic-v1"

#: A fixed, obviously-fake placeholder. The provider doesn't know or care
#: about real generation time — `torque.ai.narrative.explain_case` always
#: overwrites this field with the actual generation timestamp regardless of
#: what any provider returns (see `CaseNarrative`'s docstring). Using a
#: fixed value here (rather than `datetime.now()`) is what makes
#: `MockProvider` fully deterministic call-to-call, not just mostly so.
_PLACEHOLDER_GENERATED_AT = "1970-01-01T00:00:00+00:00"


def _extract_evidence_payload(user: str) -> dict:
    """Parse the `<evidence>...JSON...</evidence>` envelope
    `torque.ai.prompts.build_narrative_prompt` constructs. A real provider
    never does this (it just reads the text); this mock does, specifically
    so it can produce genuinely evidence-grounded output instead of an
    arbitrary hard-coded narrative.

    Uses `rindex` (last occurrence), not `index` (first occurrence), for
    the closing tag — deliberately. `build_narrative_prompt` always appends
    the literal `</evidence>` exactly once, at the very end of `user`, but
    the JSON payload between the tags may itself legitimately contain that
    same substring: it is untrusted data (`CaseEvent.reasoning` in
    particular), and an adversarial value containing literal
    `"</evidence><evidence>..."` text is exactly the kind of
    delimiter-breaking attempt this envelope must survive. Since the
    payload is valid JSON, any occurrence of `</evidence>` inside it is
    necessarily inside a quoted, escaped string value — `rindex` finding
    the real, structural closing tag (always last) rather than the first
    textual occurrence is what makes this extraction robust against that
    attempt rather than truncating the JSON mid-document.
    """
    start_tag, end_tag = "<evidence>", "</evidence>"
    start = user.index(start_tag) + len(start_tag)
    end = user.rindex(end_tag)
    return json.loads(user[start:end])


class MockProvider(LLMProvider):
    """A deterministic, evidence-grounded fake `LLMProvider`.

    Constructor flags select a single failure mode for a given instance —
    each test creates the specific `MockProvider` it needs (a "happy path"
    one, or one configured to fail in one particular way).
    """

    def __init__(
        self,
        *,
        provider_id: str = _DEFAULT_PROVIDER_ID,
        raise_exception: Exception | None = None,
        return_malformed: bool = False,
        return_wrong_type: bool = False,
        fabricate_citation: bool = False,
        wrong_case_id: bool = False,
        delay_seconds: float = 0.0,
    ) -> None:
        self._provider_id = provider_id
        self._raise_exception = raise_exception
        self._return_malformed = return_malformed
        self._return_wrong_type = return_wrong_type
        self._fabricate_citation = fabricate_citation
        self._wrong_case_id = wrong_case_id
        self._delay_seconds = delay_seconds

    def provider_id(self) -> str:
        return self._provider_id

    async def structured_generate(
        self,
        *,
        system: str,
        user: str,
        schema: type[BaseModel],
        max_tokens: int,
        timeout_s: float,
    ) -> BaseModel:
        del system, max_tokens, timeout_s  # unused by this deterministic mock

        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

        if self._raise_exception is not None:
            raise self._raise_exception

        if self._return_wrong_type:
            return "not a BaseModel instance"  # type: ignore[return-value]

        payload = _extract_evidence_payload(user)

        if self._return_malformed:
            # Deliberately missing every required field but `case_id` --
            # mirrors what a real provider's malformed JSON response would
            # produce once parsed against the schema: a natural
            # pydantic.ValidationError, not a hand-raised one.
            return schema.model_validate({"case_id": payload["current_case"]["case_id"]})

        raw = self._build_narrative_dict(payload)
        return schema.model_validate(raw)

    # --- deterministic, evidence-grounded construction ---------------------

    def _build_narrative_dict(self, payload: dict) -> dict:
        current = payload["current_case"]
        precedent_cases = payload["precedent_cases"]
        snapshot = current["snapshot"]
        snapshot_ref = snapshot["reference"]["reference_id"]
        status = snapshot["status"]
        root_cause_code = snapshot.get("root_cause_code")

        current_state = {
            "claim": f"The case is currently {status}.",
            "citation_ids": [snapshot_ref],
        }
        root_cause_explanation = (
            {
                "claim": f"The diagnosed root cause is {root_cause_code}.",
                "citation_ids": [snapshot_ref],
            }
            if root_cause_code
            else {
                "claim": "No diagnosis has been recorded for this case yet.",
                "citation_ids": [],
            }
        )
        timeline = [
            {
                "claim": f"Event: {entry['event_type']} recorded by {entry['actor']}.",
                "citation_ids": [entry["reference"]["reference_id"]],
            }
            for entry in current["timeline"]
        ]
        actions_taken = [
            {
                "claim": f"Action {action['action_type']} outcome: {action['outcome']}.",
                "citation_ids": [action["reference"]["reference_id"]],
            }
            for action in current["actions"]
        ]
        guardrail_explanation = [
            {
                "claim": (
                    f"Action {action['action_type']} was blocked by a guardrail "
                    f"({action['block_reason']})."
                ),
                "citation_ids": [action["reference"]["reference_id"]],
            }
            for action in current["actions"]
            if action.get("outcome") == "BLOCKED_BY_GUARDRAIL"
        ]

        if precedent_cases:
            precedent = {
                "found": True,
                "cases": precedent_cases,
                "note": f"{len(precedent_cases)} comparable resolved case(s) found.",
            }
        else:
            precedent = {"found": False, "cases": [], "note": NO_PRECEDENT_NOTE}

        evidence_gaps = current.get("evidence_gaps", [])
        uncertainty = (
            "Some evidence is missing: " + "; ".join(evidence_gaps)
            if evidence_gaps
            else "No known evidence gaps."
        )
        recommended_human_attention = (
            "Review this case manually; evidence gaps remain." if evidence_gaps else None
        )

        used_ids: list[str] = []
        for entry in (
            current_state,
            root_cause_explanation,
            *timeline,
            *actions_taken,
            *guardrail_explanation,
        ):
            for cid in entry["citation_ids"]:
                if cid not in used_ids:
                    used_ids.append(cid)
        for p in precedent_cases:
            if p["evidence_id"] not in used_ids:
                used_ids.append(p["evidence_id"])

        if self._fabricate_citation:
            fabricated_id = "case_event:fabricated-does-not-exist"
            used_ids.append(fabricated_id)
            timeline = [
                *timeline,
                {"claim": "A fabricated, unresolvable claim.", "citation_ids": [fabricated_id]},
            ]

        return {
            "case_id": "00000000-0000-0000-0000-000000000000"
            if self._wrong_case_id
            else current["case_id"],
            "generated_at": _PLACEHOLDER_GENERATED_AT,
            "summary": f"Case {current['case_id']} is currently {status}.",
            "current_state": current_state,
            "root_cause_explanation": root_cause_explanation,
            "timeline": timeline,
            "actions_taken": actions_taken,
            "guardrail_explanation": guardrail_explanation,
            "precedent": precedent,
            "recommended_human_attention": recommended_human_attention,
            "uncertainty": uncertainty,
            "evidence_gaps": evidence_gaps,
            "citations": [{"evidence_id": cid} for cid in used_ids],
            "provider_id": self._provider_id,
            "prompt_version": "mock-provider-does-not-know-the-real-version",
        }


__all__ = ["MockProvider"]
