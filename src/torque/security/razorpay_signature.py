"""Razorpay webhook signature verification — Blueprint Section 2.5 / Decision L.

Hard requirements this helper exists to satisfy:

* HMAC-SHA256 over the **raw, unparsed request body** — re-serialised JSON will
  not match, by design.
* Compared in **constant time**.
* Live and Test secrets are distinct — the caller selects the right one; this
  function never guesses.

This is a pure function. The HTTP endpoint that reads the raw body, calls this
BEFORE parsing, and drops failures silently (HTTP 200, no `Event` row) is
Module 2.
"""

from __future__ import annotations

import hashlib
import hmac


def compute_razorpay_signature(raw_body: bytes, secret: str) -> str:
    """The expected hex digest for `raw_body` under `secret`."""
    if not isinstance(raw_body, (bytes, bytearray)):
        raise TypeError(
            "raw_body must be the raw request bytes, not a parsed/re-serialised "
            f"object (got {type(raw_body).__name__})"
        )
    if not secret:
        raise ValueError("secret must be a non-empty string")
    return hmac.new(secret.encode("utf-8"), bytes(raw_body), hashlib.sha256).hexdigest()


def verify_razorpay_signature(
    raw_body: bytes, signature_header: str | None, secret: str
) -> bool:
    """True iff `signature_header` matches the HMAC-SHA256 of `raw_body` under
    `secret`. Constant-time comparison. A missing/empty header is False, never
    an exception (the caller drops the request silently either way)."""
    if not signature_header:
        return False
    expected = compute_razorpay_signature(raw_body, secret)
    return hmac.compare_digest(expected, signature_header)
