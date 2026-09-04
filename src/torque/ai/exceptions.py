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
