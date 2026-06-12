"""PC.14 — the transactional-email seam (mediahub.notify.email).

Unconfigured is an explicit, honest state (EmailNotConfigured — never a
pretend send); configured posts a Resend-shaped payload; headers can't be
injected; per-recipient failures don't stop a breach notice.
"""

from __future__ import annotations

import pytest

from mediahub.notify import email as te


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_123")
    monkeypatch.setenv("MEDIAHUB_EMAIL_FROM", "MediaHub <no-reply@example.org>")
    monkeypatch.delenv("MEDIAHUB_EMAIL_ENDPOINT", raising=False)


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code


def test_unconfigured_is_explicit(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("MEDIAHUB_EMAIL_FROM", raising=False)
    assert te.email_configured() is False
    with pytest.raises(te.EmailNotConfigured):
        te.send_email("a@b.co", "subject", "text")


def test_key_without_from_is_still_unconfigured(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_123")
    monkeypatch.delenv("MEDIAHUB_EMAIL_FROM", raising=False)
    assert te.email_configured() is False


def test_send_posts_resend_shape(configured, monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update({"url": url, "json": json, "headers": headers})
        return _Resp(200)

    monkeypatch.setattr("requests.post", fake_post)
    assert te.send_email("coach@club.org", "Hello", "Body text", html="<p>Body</p>")
    assert captured["url"] == te.DEFAULT_ENDPOINT
    assert captured["headers"]["Authorization"] == "Bearer re_test_123"
    assert captured["json"]["from"] == "MediaHub <no-reply@example.org>"
    assert captured["json"]["to"] == ["coach@club.org"]
    assert captured["json"]["subject"] == "Hello"
    assert captured["json"]["text"] == "Body text"
    assert captured["json"]["html"] == "<p>Body</p>"


def test_header_injection_is_stripped(configured, monkeypatch):
    captured = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured.update(json)
        return _Resp(200)

    monkeypatch.setattr("requests.post", fake_post)
    te.send_email("coach@club.org", "Hi\r\nBcc: evil@x.com", "text")
    assert "\n" not in captured["subject"] and "\r" not in captured["subject"]


def test_malformed_recipient_refused(configured):
    with pytest.raises(te.EmailSendError):
        te.send_email("not-an-email", "s", "t")


def test_provider_rejection_raises(configured, monkeypatch):
    monkeypatch.setattr("requests.post", lambda *a, **k: _Resp(422))
    with pytest.raises(te.EmailSendError):
        te.send_email("coach@club.org", "s", "t")


def test_send_to_many_isolates_failures(configured, monkeypatch):
    def fake_post(url, json=None, headers=None, timeout=None):
        return _Resp(500 if json["to"] == ["bad@club.org"] else 200)

    monkeypatch.setattr("requests.post", fake_post)
    result = te.send_to_many(["a@club.org", "bad@club.org", "c@club.org"], "s", "t")
    assert result == {"sent": 2, "failed": ["bad@club.org"]}


def test_send_to_many_surfaces_unconfigured(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("MEDIAHUB_EMAIL_FROM", raising=False)
    with pytest.raises(te.EmailNotConfigured):
        te.send_to_many(["a@club.org"], "s", "t")


def test_custom_endpoint_override(configured, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_EMAIL_ENDPOINT", "https://bridge.internal/emails")
    captured = {}

    def fake_post(url, **k):
        captured["url"] = url
        return _Resp(200)

    monkeypatch.setattr("requests.post", fake_post)
    te.send_email("coach@club.org", "s", "t")
    assert captured["url"] == "https://bridge.internal/emails"
