"""1.21 webhooks — HMAC-SHA256 request signing."""

from __future__ import annotations

from mediahub.webhooks import signing


def test_sign_verify_roundtrip():
    body = b'{"type":"card.approved"}'
    header = signing.signature_header("whsec_secret", body, timestamp=1_700_000_000)
    assert header.startswith("t=1700000000,v1=")
    assert signing.verify("whsec_secret", header, body, now=1_700_000_000)


def test_tampered_body_fails():
    body = b'{"amount":1}'
    header = signing.signature_header("whsec_secret", body, timestamp=1000)
    assert not signing.verify("whsec_secret", header, b'{"amount":999}', now=1000)


def test_wrong_secret_fails():
    body = b"x"
    header = signing.signature_header("whsec_a", body, timestamp=1000)
    assert not signing.verify("whsec_b", header, body, now=1000)


def test_stale_timestamp_rejected():
    body = b"x"
    header = signing.signature_header("whsec_a", body, timestamp=1000)
    # Far outside the tolerance window.
    assert not signing.verify("whsec_a", header, body, now=1000 + 10_000)
    # Inside the window is fine.
    assert signing.verify("whsec_a", header, body, now=1000 + 100)


def test_malformed_header_is_false():
    assert not signing.verify("s", "", b"x", now=1)
    assert not signing.verify("s", "garbage", b"x", now=1)
    assert not signing.verify("s", "t=abc,v1=def", b"x", now=1)


def test_compute_is_deterministic():
    a = signing.compute("s", 5, b"body")
    b = signing.compute("s", 5, b"body")
    assert a == b and len(a) == 64  # sha256 hex
