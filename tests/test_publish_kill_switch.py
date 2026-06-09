"""Tests for the global publishing kill switch (P2.3).

Covers:
  * Default (unset) state is disengaged; assert_publishing_allowed() is a no-op.
  * Truthy env values engage the switch and make assert_publishing_allowed() raise.
  * Falsy env values keep the switch disengaged.
  * kill_switch_status() shape is correct for both states.
  * schedule_post() raises PublishingHalted and makes NO requests.post call when engaged.
  * schedule_post() proceeds to the network layer when disengaged.
  * GET /healthz/deps returns 200 with deps["publish_kill_switch"]["engaged"]
    reflecting the env, and an engaged switch does not break the response.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mediahub.publishing.kill_switch import (
    KILL_SWITCH_ENV,
    PublishingHalted,
    assert_publishing_allowed,
    kill_switch_status,
    publish_kill_switch_engaged,
)
import mediahub.publishing.buffer as buffer_mod
from mediahub.publishing.buffer import schedule_post


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.ok = 200 <= status_code < 300
        self.headers = {}

    def json(self):
        return self._payload


def _fake_requests(*, post_resp=None):
    """Return a fake requests namespace; raises AssertionError if .post is called unexpectedly."""

    def _sentinel_post(*a, **kw):
        raise AssertionError("requests.post must NOT be called when the kill switch is engaged")

    return SimpleNamespace(
        get=lambda *a, **kw: _FakeResp(200, []),
        post=post_resp or _sentinel_post,
        RequestException=Exception,
    )


# ---------------------------------------------------------------------------
# publish_kill_switch_engaged()
# ---------------------------------------------------------------------------


def test_default_unset_is_disengaged(monkeypatch):
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    assert publish_kill_switch_engaged() is False


def test_blank_env_is_disengaged(monkeypatch):
    monkeypatch.setenv(KILL_SWITCH_ENV, "")
    assert publish_kill_switch_engaged() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on", "engaged", "  on  "])
def test_truthy_values_engage(monkeypatch, value):
    monkeypatch.setenv(KILL_SWITCH_ENV, value)
    assert publish_kill_switch_engaged() is True


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no", "  "])
def test_falsy_values_stay_disengaged(monkeypatch, value):
    monkeypatch.setenv(KILL_SWITCH_ENV, value)
    assert publish_kill_switch_engaged() is False


# ---------------------------------------------------------------------------
# assert_publishing_allowed()
# ---------------------------------------------------------------------------


def test_assert_allowed_is_noop_when_disengaged(monkeypatch):
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    assert_publishing_allowed()  # must not raise


def test_assert_allowed_raises_when_engaged(monkeypatch):
    monkeypatch.setenv(KILL_SWITCH_ENV, "1")
    with pytest.raises(PublishingHalted) as exc_info:
        assert_publishing_allowed()
    msg = str(exc_info.value)
    assert "No post was sent" in msg
    assert "kill switch" in msg.lower()


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "Yes", "on", "engaged", "  on  "])
def test_assert_raises_for_all_truthy(monkeypatch, value):
    monkeypatch.setenv(KILL_SWITCH_ENV, value)
    with pytest.raises(PublishingHalted):
        assert_publishing_allowed()


# ---------------------------------------------------------------------------
# kill_switch_status()
# ---------------------------------------------------------------------------


def test_status_shape_disengaged(monkeypatch):
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    status = kill_switch_status()
    assert status["engaged"] is False
    assert status["env"] == KILL_SWITCH_ENV
    assert "configured" in status


def test_status_shape_engaged(monkeypatch):
    monkeypatch.setenv(KILL_SWITCH_ENV, "1")
    status = kill_switch_status()
    assert status["engaged"] is True
    assert status["env"] == KILL_SWITCH_ENV
    assert status["configured"] == "1"


# ---------------------------------------------------------------------------
# schedule_post() integration
# ---------------------------------------------------------------------------


def test_schedule_post_raises_and_no_requests_when_engaged(monkeypatch):
    monkeypatch.setenv(KILL_SWITCH_ENV, "1")
    fake_reqs = _fake_requests()  # .post raises AssertionError if called
    monkeypatch.setattr(buffer_mod, "requests", fake_reqs)

    with pytest.raises(PublishingHalted):
        schedule_post(token="tok", channel_id="ch1", text="hello world")


def test_schedule_post_proceeds_when_disengaged(monkeypatch):
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)

    call_count = []

    def _fake_post(*a, **kw):
        call_count.append(1)
        return _FakeResp(
            200,
            {
                "success": True,
                "updates": [{"id": "upd_123"}],
            },
        )

    fake_reqs = SimpleNamespace(
        get=lambda *a, **kw: _FakeResp(200, []),
        post=_fake_post,
        RequestException=Exception,
    )
    monkeypatch.setattr(buffer_mod, "requests", fake_reqs)

    result = schedule_post(token="tok", channel_id="ch1", text="hello world")
    assert result["ok"] is True
    assert result["update_id"] == "upd_123"
    assert len(call_count) == 1


# ---------------------------------------------------------------------------
# Flask /healthz/deps integration
# ---------------------------------------------------------------------------


@pytest.fixture()
def app(tmp_path):
    """Minimal Flask test app with DATA_DIR isolated."""
    import os

    os.environ.setdefault("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    return application


def test_healthz_deps_includes_kill_switch_unset(monkeypatch, app):
    monkeypatch.delenv(KILL_SWITCH_ENV, raising=False)
    with app.test_client() as client:
        resp = client.get("/healthz/deps")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "publish_kill_switch" in body["deps"]
    assert body["deps"]["publish_kill_switch"]["engaged"] is False


def test_healthz_deps_includes_kill_switch_engaged(monkeypatch, app):
    monkeypatch.setenv(KILL_SWITCH_ENV, "1")
    with app.test_client() as client:
        resp = client.get("/healthz/deps")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["deps"]["publish_kill_switch"]["engaged"] is True
    # The ok flag must NOT be affected by the kill switch state.
    # (ok is derived only from playwright/node/remotion)
    assert "ok" in body
