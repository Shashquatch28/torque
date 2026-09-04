"""AI-subsystem exceptions.

Kept in their own module (rather than added to `torque.exceptions`) because
`torque.ai` is architecturally isolated from the deterministic core (see the
package docstring) — its own error vocabulary lives with it. Both subclass
the shared `torque.exceptions.TorqueError` base so callers can still catch
broadly across the whole codebase if they choose to.

`torque.exceptions` itself is plain exception-class definitions with no
state and no mutation capability — importing it does not cross the
read/write boundary this package enforces.
"""

from __future__ import annotations

from torque.exceptions import TorqueError


class AIError(TorqueError):
    """Base class for every `torque.ai` error."""


class EvidenceNotFoundError(AIError):
    """No case exists for the given `(merchant_id, case_id)`.

    Deliberately never distinguishes "unknown case" from "case belongs to a
    different merchant" — the same never-a-cross-tenant-leak posture as
    `torque.exceptions.CaseNotFoundError` (Blueprint §10.8).
    """


class NarrativeGenerationError(AIError):
    """Phase 4 — `torque.ai.narrative.explain_case` could not produce a
    trustworthy `CaseNarrative`.

    Raised for every provider failure mode: an exception from the provider
    (timeout, network error, ...), a response that fails `CaseNarrative`
    schema validation, or a response containing a citation id that does not
    resolve against the evidence actually supplied to the generation call.
    `explain_case` never returns a partial, repaired, or best-guess
    narrative in any of these cases — this exception is the only failure
    signal, and the original provider exception (if any) is chained via
    `from exc` for local debugging, never re-exposed verbatim as the
    caller-facing message. The deterministic evidence
    (`torque.ai.evidence.gather_case_evidence`) is entirely unaffected by
    this failure — it is read separately and first, and nothing about its
    own success or content depends on generation succeeding afterward.
    """
