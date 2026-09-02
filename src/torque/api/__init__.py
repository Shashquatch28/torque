"""Torque HTTP surface (Blueprint Part B, Module 2 — Signal Ingestion).

Milestone 7a introduces the first real route: the Razorpay webhook endpoint that
verifies HMAC-SHA256 over the raw body *before* parsing, drops any request that
fails verification (or is a duplicate) with HTTP 200 and no side effect, and
writes exactly one deduplicated ``Event`` row for everything else.

Out of scope for M7a and NOT here yet: the 90s/30s self-recovery buffer,
BullMQ/Redis, cross-leg dedup, systemic detection, case creation, retry-budget
seeding, the checkout-abandoned path, and dispatch to Module 3.
"""

from __future__ import annotations

from torque.api.app import create_app

__all__ = ["create_app"]
