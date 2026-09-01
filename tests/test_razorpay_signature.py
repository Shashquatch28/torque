"""Blueprint Section 2.5 / Decision L — HMAC-SHA256 over the RAW body,
constant-time compare, distinct Live/Test secrets."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from torque.security.razorpay_signature import (
    compute_razorpay_signature,
    verify_razorpay_signature,
)

SECRET = "whsec_live_example"
RAW = b'{"event":"payment.failed","payload":{"amount":50000}}'


def _sig(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_passes():
    assert verify_razorpay_signature(RAW, _sig(RAW, SECRET), SECRET) is True


def test_tampered_body_fails():
    assert verify_razorpay_signature(RAW + b" ", _sig(RAW, SECRET), SECRET) is False


def test_reserialized_json_does_not_match():
    # Re-serialising changes byte layout (spaces, key order) -> must not verify.
    reserialized = json.dumps(json.loads(RAW)).encode()
    assert reserialized != RAW
    assert verify_razorpay_signature(reserialized, _sig(RAW, SECRET), SECRET) is False


def test_wrong_secret_fails():
    assert verify_razorpay_signature(RAW, _sig(RAW, SECRET), "whsec_test_other") is False


def test_missing_signature_is_false_not_error():
    assert verify_razorpay_signature(RAW, None, SECRET) is False
    assert verify_razorpay_signature(RAW, "", SECRET) is False


def test_compute_rejects_non_bytes():
    with pytest.raises(TypeError):
        compute_razorpay_signature("not-bytes", SECRET)  # type: ignore[arg-type]


def test_compute_rejects_empty_secret():
    with pytest.raises(ValueError):
        compute_razorpay_signature(RAW, "")


def test_uses_constant_time_compare(monkeypatch):
    calls = {"n": 0}
    real = hmac.compare_digest

    def spy(a, b):
        calls["n"] += 1
        return real(a, b)

    monkeypatch.setattr("torque.security.razorpay_signature.hmac.compare_digest", spy)
    verify_razorpay_signature(RAW, _sig(RAW, SECRET), SECRET)
    assert calls["n"] == 1
