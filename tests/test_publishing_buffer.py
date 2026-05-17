"""Buffer publishing layer tests.

Covers:
  * publishing.buffer.list_channels — success + failure paths
  * publishing.buffer.schedule_post — success + failure paths
  * Both helpers raise BufferAuthError when token is missing/blank
  * /settings Buffer save/clear round-trip
  * /api/buffer/channels — 401 when no token, 200 with mocked channels
  * /api/runs/<id>/card/<cid>/schedule — happy path, missing-token,
    Buffer-failure (caption preserved)
  * Card workflow state gains schedule_status="scheduled" on success

External HTTP is patched out via monkeypatch — no live Buffer calls.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from mediahub.web import secrets_store
from mediahub.web.web import create_app
from mediahub.publishing import buffer as buffer_mod
from mediahub.publishing.buffer import (
    BufferAPIError,
    BufferAuthError,
    list_channels,
    schedule_post,
)
from mediahub.workflow.status import CardWorkflowState, ScheduleStatus
from mediahub.workflow.store import WorkflowStore


# ---------------------------------------------------------------------
# Fake `requests` response helpers
# ---------------------------------------------------------------------

class _FakeResp:
    def __init__(self, status_code, payload=None, *, raise_on_json=False):
        self.status_code = status_code
        self._payload = payload
        self._raise = raise_on_json
        self.ok = 200 <= status_code < 300

    def json(self):
        if self._raise:
            raise ValueError("not json")
        return self._payload


def _patch_requests(monkeypatch, *, get=None, post=None):
    """Patch buffer_mod.requests.get / .post with the given callables."""
    fake = SimpleNamespace(
        get=get or (lambda *a, **kw: _FakeResp(500, {})),
        post=post or (lambda *a, **kw: _FakeResp(500, {})),
        RequestException=Exception,
    )
    monkeypatch.setattr(buffer_mod, "requests", fake)


# ---------------------------------------------------------------------
# Direct client tests
# ---------------------------------------------------------------------

def test_list_channels_missing_token_raises_auth_error():
    with pytest.raises(BufferAuthError) as exc:
        list_channels("")
    assert "Connect Buffer" in str(exc.value)
    with pytest.raises(BufferAuthError):
        list_channels(None)  # type: ignore[arg-type]
    with pytest.raises(BufferAuthError):
        list_channels("   ")


def test_list_channels_success(monkeypatch):
    payload = [
        {
            "id": "5b1a",
            "service": "instagram",
            "service_username": "@swansea_uni_swim",
            "formatted_username": "Swansea Uni Swim",
            "avatar": "https://x/avatar.png",
            "default": True,
        },
        {
            "id": "5b1b",
            "service": "twitter",
            "service_username": "@suswim",
            "formatted_username": "SU Swim",
            "default": False,
        },
    ]
    captured = {}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _FakeResp(200, payload)

    _patch_requests(monkeypatch, get=fake_get)
    out = list_channels("token-xyz")
    assert captured["url"] == "https://api.bufferapp.com/1/profiles.json"
    assert captured["params"] == {"access_token": "token-xyz"}
    assert len(out) == 2
    assert out[0]["id"] == "5b1a"
    assert out[0]["service"] == "instagram"
    assert out[0]["formatted_username"] == "Swansea Uni Swim"
    assert out[0]["default"] is True
    assert out[1]["default"] is False


def test_list_channels_401_raises_auth_error(monkeypatch):
    _patch_requests(monkeypatch, get=lambda *a, **kw: _FakeResp(401, {"error": "Unauthenticated"}))
    with pytest.raises(BufferAuthError):
        list_channels("bad-token")


def test_list_channels_500_raises_api_error(monkeypatch):
    _patch_requests(monkeypatch, get=lambda *a, **kw: _FakeResp(500, {"message": "boom"}))
    with pytest.raises(BufferAPIError) as exc:
        list_channels("token")
    assert "boom" in str(exc.value)


def test_list_channels_transport_error_raises_api_error(monkeypatch):
    class _Err(Exception):
        pass

    def boom(*a, **kw):
        raise _Err("dns")

    fake = SimpleNamespace(get=boom, post=boom, RequestException=_Err)
    monkeypatch.setattr(buffer_mod, "requests", fake)
    with pytest.raises(BufferAPIError) as exc:
        list_channels("token")
    assert "dns" in str(exc.value)


def test_schedule_post_missing_token_raises_auth_error():
    with pytest.raises(BufferAuthError):
        schedule_post("", channel_id="cid", text="hello")
    with pytest.raises(BufferAuthError):
        schedule_post("   ", channel_id="cid", text="hello")


def test_schedule_post_missing_channel_or_text_raises_api_error():
    with pytest.raises(BufferAPIError):
        schedule_post("tok", channel_id="", text="hello")
    with pytest.raises(BufferAPIError):
        schedule_post("tok", channel_id="cid", text="")


def test_schedule_post_success(monkeypatch):
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured["url"] = url
        captured["data"] = list(data or [])
        return _FakeResp(200, {
            "success": True,
            "buffer_count": 1,
            "updates": [{"id": "update-123", "status": "buffer"}],
        })

    _patch_requests(monkeypatch, post=fake_post)
    res = schedule_post(
        "tok-1",
        channel_id="cid-1",
        text="Big win for the club today!",
        media_urls=["https://example.com/img.jpg"],
    )
    assert captured["url"] == "https://api.bufferapp.com/1/updates/create.json"
    data_dict = dict(captured["data"])
    assert data_dict["access_token"] == "tok-1"
    assert data_dict["text"] == "Big win for the club today!"
    assert data_dict["profile_ids[]"] == "cid-1"
    assert data_dict["media[link]"] == "https://example.com/img.jpg"
    assert res["ok"] is True
    assert res["update_id"] == "update-123"
    assert res["channel_id"] == "cid-1"


def test_schedule_post_with_scheduled_at_sends_timestamp(monkeypatch):
    from datetime import datetime, timezone
    captured = {}

    def fake_post(url, data=None, timeout=None):
        captured["data"] = list(data or [])
        return _FakeResp(200, {"updates": [{"id": "uid"}]})

    _patch_requests(monkeypatch, post=fake_post)
    when = datetime(2026, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
    schedule_post("tok", channel_id="cid", text="hi", scheduled_at=when)
    data_dict = dict(captured["data"])
    assert "scheduled_at" in data_dict
    assert data_dict["scheduled_at"] == str(int(when.timestamp()))


def test_schedule_post_401_raises_auth_error(monkeypatch):
    _patch_requests(monkeypatch, post=lambda *a, **kw: _FakeResp(403, {"error": "forbidden"}))
    with pytest.raises(BufferAuthError):
        schedule_post("tok", channel_id="cid", text="hi")


def test_schedule_post_api_error_includes_buffer_message(monkeypatch):
    _patch_requests(monkeypatch, post=lambda *a, **kw: _FakeResp(
        400, {"message": "Profile has reached its queue limit."}
    ))
    with pytest.raises(BufferAPIError) as exc:
        schedule_post("tok", channel_id="cid", text="hi")
    assert "queue limit" in str(exc.value)


def test_schedule_post_no_update_id_raises_api_error(monkeypatch):
    _patch_requests(monkeypatch, post=lambda *a, **kw: _FakeResp(
        200, {"success": True, "updates": []}
    ))
    with pytest.raises(BufferAPIError):
        schedule_post("tok", channel_id="cid", text="hi")


# ---------------------------------------------------------------------
# Web app integration tests
# ---------------------------------------------------------------------

@pytest.fixture
def app(tmp_path, monkeypatch):
    fake_secrets = tmp_path / "secrets.json"
    monkeypatch.setattr(secrets_store, "_SECRETS_PATH", fake_secrets)
    monkeypatch.delenv("BUFFER_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("MEDIAHUB_DISABLE_CLAUDE_CLI", "1")
    a = create_app()
    a.config["TESTING"] = True
    return a


def test_api_buffer_channels_no_token_returns_401(app):
    c = app.test_client()
    r = c.get("/api/buffer/channels")
    assert r.status_code == 401
    j = r.get_json()
    assert j["connected"] is False
    assert j["error"] == "no_token"
    assert "administrator" in j["message"].lower()
    # settings_url still points at /settings but that route now redirects to home


def test_api_buffer_channels_returns_channels(app, monkeypatch):
    monkeypatch.setenv("BUFFER_ACCESS_TOKEN", "1/test-token")
    monkeypatch.setattr(
        "mediahub.publishing.buffer.list_channels",
        lambda token: [
            {"id": "p1", "service": "instagram",
             "service_username": "@one", "formatted_username": "One",
             "avatar": None, "default": True},
            {"id": "p2", "service": "twitter",
             "service_username": "@two", "formatted_username": "Two",
             "avatar": None, "default": False},
        ],
    )
    c = app.test_client()
    r = c.get("/api/buffer/channels")
    assert r.status_code == 200
    j = r.get_json()
    assert j["connected"] is True
    assert j["count"] == 2
    assert j["channels"][0]["id"] == "p1"


def test_api_buffer_channels_auth_error_returns_401(app, monkeypatch):
    monkeypatch.setenv("BUFFER_ACCESS_TOKEN", "1/bad-token")

    def boom(token):
        raise BufferAuthError("Buffer rejected the access token.")

    monkeypatch.setattr("mediahub.publishing.buffer.list_channels", boom)
    c = app.test_client()
    r = c.get("/api/buffer/channels")
    assert r.status_code == 401
    j = r.get_json()
    assert j["connected"] is False
    assert "rejected" in j["message"].lower()


def test_api_schedule_no_token_returns_401_and_preserves_caption(app):
    c = app.test_client()
    r = c.post(
        "/api/runs/run123/card/swim456/schedule",
        json={"channel_ids": ["p1"], "caption": "My edited caption"},
    )
    assert r.status_code == 401
    j = r.get_json()
    assert j["ok"] is False
    assert j["error"] == "no_token"
    assert j["caption"] == "My edited caption"


def test_api_schedule_rejects_empty_channels(app, monkeypatch):
    monkeypatch.setenv("BUFFER_ACCESS_TOKEN", "1/test")
    c = app.test_client()
    r = c.post(
        "/api/runs/r/card/c/schedule",
        json={"channel_ids": [], "caption": "hi"},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "no_channels"


def test_api_schedule_rejects_empty_caption(app, monkeypatch):
    monkeypatch.setenv("BUFFER_ACCESS_TOKEN", "1/test")
    c = app.test_client()
    r = c.post(
        "/api/runs/r/card/c/schedule",
        json={"channel_ids": ["p1"], "caption": "   "},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "no_caption"


def test_api_schedule_happy_path(app, monkeypatch, tmp_path):
    monkeypatch.setenv("BUFFER_ACCESS_TOKEN", "1/test")
    monkeypatch.setattr(
        "mediahub.publishing.buffer.schedule_post",
        lambda **kw: {"ok": True, "update_id": "u-1", "channel_id": kw["channel_id"], "raw": {}},
    )
    c = app.test_client()
    r = c.post(
        "/api/runs/run1/card/cardA/schedule",
        json={
            "channel_ids": ["p1", "p2"],
            "caption": "Hello world",
            "scheduled_at": "2026-06-01T10:00:00Z",
        },
    )
    assert r.status_code == 200, r.get_data(as_text=True)
    j = r.get_json()
    assert j["ok"] is True
    assert j["schedule_status"] == "scheduled"
    assert len(j["buffer_update_ids"]) == 2
    assert j["scheduled_at"].startswith("2026-06-01")

    # Workflow sidecar was updated
    from mediahub.web import web as _web
    ws = WorkflowStore(_web.RUNS_DIR)
    state = ws.load("run1").get("cardA")
    assert state is not None
    assert state.schedule_status == ScheduleStatus.SCHEDULED
    assert state.buffer_update_id == "u-1;u-1"
    assert state.schedule_error is None


def test_api_schedule_buffer_failure_preserves_caption_and_marks_failed(
    app, monkeypatch
):
    monkeypatch.setenv("BUFFER_ACCESS_TOKEN", "1/test")

    def fail(**kw):
        raise BufferAPIError("Profile has reached its queue limit.")

    monkeypatch.setattr("mediahub.publishing.buffer.schedule_post", fail)
    c = app.test_client()
    r = c.post(
        "/api/runs/run2/card/cardB/schedule",
        json={"channel_ids": ["p1"], "caption": "Edited copy"},
    )
    assert r.status_code == 502
    j = r.get_json()
    assert j["ok"] is False
    assert "queue limit" in j["message"]
    assert j["caption"] == "Edited copy"  # not lost

    from mediahub.web import web as _web
    ws = WorkflowStore(_web.RUNS_DIR)
    state = ws.load("run2").get("cardB")
    assert state is not None
    assert state.schedule_status == ScheduleStatus.FAILED
    assert state.schedule_error and "queue limit" in state.schedule_error


def test_api_schedule_bad_iso_time_returns_400(app, monkeypatch):
    monkeypatch.setenv("BUFFER_ACCESS_TOKEN", "1/test")
    c = app.test_client()
    r = c.post(
        "/api/runs/r/card/c/schedule",
        json={
            "channel_ids": ["p1"],
            "caption": "hi",
            "scheduled_at": "next Friday",
        },
    )
    assert r.status_code == 400
    j = r.get_json()
    assert j["error"] == "bad_time"
    assert j["caption"] == "hi"


def test_workflow_state_round_trips_schedule_fields(tmp_path):
    """CardWorkflowState.from_dict / to_dict must preserve schedule fields."""
    ws = WorkflowStore(tmp_path)
    ws.set_schedule(
        "run-x", "card-y",
        schedule_status=ScheduleStatus.SCHEDULED,
        buffer_update_id="update-1",
        scheduled_at="2026-06-01T10:00:00+00:00",
        schedule_error=None,
    )
    states = ws.load("run-x")
    assert "card-y" in states
    s = states["card-y"]
    assert s.schedule_status == ScheduleStatus.SCHEDULED
    assert s.buffer_update_id == "update-1"
    assert s.scheduled_at == "2026-06-01T10:00:00+00:00"


def test_workflow_state_backwards_compatible_with_old_sidecar(tmp_path):
    """Sidecars written before this feature must still load cleanly."""
    legacy = {
        "card-a": {
            "card_id": "card-a",
            "status": "approved",
            "edited_captions": None,
            "notes": None,
            "posted_at": None,
            "last_changed_at": "2026-05-01T00:00:00Z",
        }
    }
    path = tmp_path / "run__workflow.json"
    path.write_text(json.dumps(legacy))
    ws = WorkflowStore(tmp_path)
    states = ws.load("run")
    s = states["card-a"]
    assert s.status.value == "approved"
    assert s.schedule_status == ScheduleStatus.QUEUED
    assert s.buffer_update_id is None
