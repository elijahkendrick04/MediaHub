"""Tests for mediahub.notify (ntfy + webhook notification channels).

Offline: requests.post is faked. Covers default-OFF behaviour, the ntfy and
webhook wire formats, the no-default-topic safety rule, header-injection
stripping, non-2xx / exception handling, and the 'pack ready' convenience.
"""

from __future__ import annotations

import pytest


class _Resp:
    def __init__(self, status_code=200):
        self.status_code = status_code


class _Capture:
    def __init__(self, status=200):
        self.calls: list = []
        self.status = status

    def __call__(self, *a, **k):
        self.calls.append((a, k))
        return _Resp(self.status)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for k in (
        "MEDIAHUB_NTFY_TOPIC",
        "MEDIAHUB_NTFY_SERVER",
        "MEDIAHUB_NTFY_TOKEN",
        "MEDIAHUB_NOTIFY_WEBHOOK",
        "MEDIAHUB_NOTIFY_TIMEOUT",
    ):
        monkeypatch.delenv(k, raising=False)
    yield


def test_default_off_is_a_noop():
    from mediahub import notify

    assert notify.is_enabled() is False
    assert notify.notify("t", "m", background=False) == 0
    assert notify.notify_pack_ready("run1", background=False) == 0


def test_no_default_ntfy_topic():
    # A guessable public topic would leak notifications — so there is no default.
    from mediahub.notify.channels import NtfyChannel

    assert NtfyChannel().configured() is False


def test_ntfy_send_wire_format(monkeypatch):
    from mediahub import notify

    monkeypatch.setenv("MEDIAHUB_NTFY_TOPIC", "secret-topic")
    cap = _Capture()
    monkeypatch.setattr("requests.post", cap)

    n = notify.notify(
        "Hi",
        "Body",
        priority="high",
        tags=("white_check_mark",),
        click_url="https://e.test",
        background=False,
    )
    assert n == 1
    args, kw = cap.calls[0]
    assert args[0] == "https://ntfy.sh/secret-topic"
    assert kw["data"] == b"Body"
    assert kw["headers"]["Title"] == "Hi"
    assert kw["headers"]["Priority"] == "high"
    assert kw["headers"]["Tags"] == "white_check_mark"
    assert kw["headers"]["Click"] == "https://e.test"
    assert "Authorization" not in kw["headers"]


def test_ntfy_custom_server_and_token(monkeypatch):
    from mediahub import notify

    monkeypatch.setenv("MEDIAHUB_NTFY_TOPIC", "t")
    monkeypatch.setenv("MEDIAHUB_NTFY_SERVER", "https://push.example/")
    monkeypatch.setenv("MEDIAHUB_NTFY_TOKEN", "tok")
    cap = _Capture()
    monkeypatch.setattr("requests.post", cap)

    notify.notify("a", "b", background=False)
    args, kw = cap.calls[0]
    assert args[0] == "https://push.example/t"  # trailing slash trimmed
    assert kw["headers"]["Authorization"] == "Bearer tok"


def test_header_injection_is_stripped(monkeypatch):
    from mediahub import notify

    monkeypatch.setenv("MEDIAHUB_NTFY_TOPIC", "t")
    cap = _Capture()
    monkeypatch.setattr("requests.post", cap)

    notify.notify("line1\r\nX-Evil: 1", "body", background=False)
    title = cap.calls[0][1]["headers"]["Title"]
    assert "\n" not in title and "\r" not in title


def test_webhook_send_payload(monkeypatch):
    from mediahub import notify

    monkeypatch.setenv("MEDIAHUB_NOTIFY_WEBHOOK", "https://hook.test/x")
    cap = _Capture()
    monkeypatch.setattr("requests.post", cap)

    n = notify.notify("T", "M", background=False)
    assert n == 1
    args, kw = cap.calls[0]
    assert args[0] == "https://hook.test/x"
    body = kw["json"]
    assert body["title"] == "T" and body["message"] == "M"
    assert "T\nM" in body["text"]  # Slack renders this key
    assert body["content"] == body["text"][:2000]  # Discord requires 'content'


def test_both_channels_fire(monkeypatch):
    from mediahub import notify

    monkeypatch.setenv("MEDIAHUB_NTFY_TOPIC", "t")
    monkeypatch.setenv("MEDIAHUB_NOTIFY_WEBHOOK", "https://h.test")
    cap = _Capture()
    monkeypatch.setattr("requests.post", cap)

    assert notify.notify("a", "b", background=False) == 2
    assert len(cap.calls) == 2


def test_non_2xx_not_counted(monkeypatch):
    from mediahub import notify

    monkeypatch.setenv("MEDIAHUB_NTFY_TOPIC", "t")
    monkeypatch.setattr("requests.post", _Capture(status=500))
    assert notify.notify("a", "b", background=False) == 0


def test_send_exception_is_swallowed(monkeypatch):
    from mediahub import notify

    monkeypatch.setenv("MEDIAHUB_NTFY_TOPIC", "t")

    def boom(*a, **k):
        raise RuntimeError("net down")

    monkeypatch.setattr("requests.post", boom)
    assert notify.notify("a", "b", background=False) == 0  # never raises


def test_pack_ready_message(monkeypatch):
    from mediahub import notify

    monkeypatch.setenv("MEDIAHUB_NTFY_TOPIC", "t")
    cap = _Capture()
    monkeypatch.setattr("requests.post", cap)

    notify.notify_pack_ready("run-9", count=3, background=False)
    body = cap.calls[0][1]["data"].decode()
    assert "3 cards ready" in body and "run-9" in body
