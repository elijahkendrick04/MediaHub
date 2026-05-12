"""V8.1 Issue 3 — Settings page + non-masquerading caption endpoint.

Verifies:
  * /settings GET renders and shows the no-key state
  * POST /settings with a fake key persists to data/secrets.json
  * /api/settings/llm-status reports {live: bool}
  * Live caption endpoint with tone=ai and NO key returns
    {live: false, error: "no_key"} \u2014 i.e. no fake AI output.
  * llm._resolve_anthropic_key() picks up disk-stored key.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mediahub.web.web import create_app
from mediahub.web import secrets_store


@pytest.fixture
def app(tmp_path, monkeypatch):
    # Redirect secrets to a temp file so tests don't touch real data.
    fake_secrets = tmp_path / "secrets.json"
    monkeypatch.setattr(secrets_store, "_SECRETS_PATH", fake_secrets)
    # Ensure no env key leaks in.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("PPLX_TOOL_BRIDGE_LOCAL_URL", raising=False)
    monkeypatch.delenv("PPLX_TOOL_BRIDGE_TOKEN", raising=False)
    # Disable the claude-CLI bridge (added v9.1).
    monkeypatch.setenv("MEDIAHUB_DISABLE_CLAUDE_CLI", "1")
    # Reset cached anthropic client so the next call rebuilds.
    from mediahub.media_ai import llm as _llm
    _llm._anthropic_client = None
    _llm._anthropic_client_key = None
    a = create_app()
    a.config["TESTING"] = True
    return a


def test_settings_get_renders(app):
    c = app.test_client()
    r = c.get("/settings")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Settings" in body
    assert "Anthropic" in body
    assert "Live AI captions DISABLED" in body


def test_llm_status_no_key(app):
    c = app.test_client()
    r = c.get("/api/settings/llm-status")
    assert r.status_code == 200
    j = r.get_json()
    assert j["live"] is False
    assert j["provider"] is None


def test_settings_post_persists_key(app):
    c = app.test_client()
    fake = "sk-ant-" + "x" * 40
    r = c.post("/settings", data={"anthropic_api_key": fake},
               follow_redirects=False)
    assert r.status_code == 200
    assert "saved" in r.get_data(as_text=True).lower()
    # Stored on disk
    assert secrets_store.get_secret("anthropic_api_key") == fake
    # File mode 0600 where supported
    p = secrets_store._SECRETS_PATH
    if os.name == "posix":
        mode = oct(p.stat().st_mode)[-3:]
        assert mode == "600", f"expected 0600, got {mode}"

    # Status flips to live=True
    r2 = c.get("/api/settings/llm-status")
    j = r2.get_json()
    assert j["live"] is True
    assert j["provider"] == "anthropic"
    assert "x" not in j["masked"][:6]  # masked, not echoed in full


def test_settings_post_rejects_garbage(app):
    c = app.test_client()
    r = c.post("/settings", data={"anthropic_api_key": "garbage"})
    assert r.status_code == 200
    assert secrets_store.get_secret("anthropic_api_key") is None


def test_settings_clear_key(app):
    c = app.test_client()
    fake = "sk-ant-" + "y" * 40
    secrets_store.set_secret("anthropic_api_key", fake)
    assert secrets_store.get_secret("anthropic_api_key") == fake
    r = c.post("/settings", data={"action": "clear_anthropic"})
    assert r.status_code == 200
    assert secrets_store.get_secret("anthropic_api_key") is None


def test_caption_endpoint_no_key_returns_live_false(app, tmp_path, monkeypatch):
    """The masquerade-killer test \u2014 spec demands no fake AI output."""
    # Stub a run with one ranked achievement so the endpoint can find it.
    from mediahub.web import web as _web
    fake_run = {
        "profile_display": "Test Club",
        "meet": {"name": "Test Meet"},
        "recognition_report": {
            "ranked_achievements": [
                {"achievement": {
                    "swim_id": "abc123",
                    "swimmer_name": "Jane Doe",
                    "event": "100 Free",
                    "time": "1:02.34",
                    "pb": True,
                    "place": 1,
                    "type": "PB",
                    "headline": "First place",
                }}
            ]
        },
    }
    monkeypatch.setattr(_web, "_load_run", lambda rid: fake_run)
    c = app.test_client()
    r = c.post("/api/runs/test_run/swim/abc123/caption?tone=ai")
    assert r.status_code == 200
    j = r.get_json()
    assert j["tone"] == "ai"
    assert j["live"] is False, f"expected live=False with no key, got: {j!r}"
    assert j["error"] == "no_key"
    assert j["caption"] == ""
    assert "Settings" in j["message"]


def test_llm_resolve_picks_up_disk_key(app):
    """media_ai.llm._resolve_anthropic_key reads disk store when env empty."""
    from mediahub.media_ai import llm as _llm
    fake = "sk-ant-" + "z" * 40
    secrets_store.set_secret("anthropic_api_key", fake)
    assert _llm._resolve_anthropic_key() == fake
    assert _llm._has_anthropic_key() is True
    assert _llm.is_available() is True
