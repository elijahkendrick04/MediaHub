"""Settings-page-removal + caption-no-key behaviour.

The settings page is gone — operator credentials are now exclusively
env-var configured at deploy time. This test file pins what's left:

  • /settings 302-redirects to home so old bookmarks don't 404
  • /api/settings/llm-status remains a read-only status endpoint
  • The caption endpoint with no LLM key returns
    {live: false, error: "no_key", message: <admin-facing copy>}
  • env-var key resolution still works for the LLM layer
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from mediahub.web.web import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    """Clean env so no LLM provider leaks in from the host."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    # Point the disk-fallback at a non-existent path so secrets_store
    # is genuinely empty.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Force re-resolution of cached module-level paths.
    import importlib
    import mediahub.web.secrets_store as _ss
    importlib.reload(_ss)
    # Reset the cached anthropic client.
    from mediahub.media_ai import llm as _llm
    _llm._anthropic_client = None
    _llm._anthropic_client_key = None
    a = create_app()
    a.config["TESTING"] = True
    return a


# ---------------------------------------------------------------------------
# /settings now redirects to home
# ---------------------------------------------------------------------------

def test_settings_redirects_to_home(app):
    c = app.test_client()
    r = c.get("/settings", follow_redirects=False)
    assert r.status_code in (301, 302, 303, 307, 308)
    # The redirect target must be home.
    location = r.headers.get("Location", "")
    assert location.endswith("/") or location == "" or location.endswith("/home")


# ---------------------------------------------------------------------------
# /api/settings/llm-status — read-only status endpoint
# ---------------------------------------------------------------------------

def test_llm_status_no_key_reports_offline(app):
    c = app.test_client()
    r = c.get("/api/settings/llm-status")
    assert r.status_code == 200
    j = r.get_json()
    assert j["live"] is False
    assert j["provider"] is None


def test_llm_status_with_gemini_env_reports_live(app, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-fake-test-key-1234567890")
    c = app.test_client()
    r = c.get("/api/settings/llm-status")
    j = r.get_json()
    assert j["live"] is True
    assert j["provider"] == "gemini"


def test_llm_status_with_anthropic_env_reports_live(app, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-test-key-1234567890")
    c = app.test_client()
    r = c.get("/api/settings/llm-status")
    j = r.get_json()
    assert j["live"] is True
    # Gemini default-prefers; with only Anthropic configured, Anthropic wins.
    assert j["provider"] == "anthropic"


# ---------------------------------------------------------------------------
# Caption endpoint with no key — surface "contact administrator" honestly
# ---------------------------------------------------------------------------

def test_caption_endpoint_no_key_returns_live_false(app, tmp_path, monkeypatch):
    """No silent fake captions. When the operator hasn't configured a
    provider, the user sees an honest "AI features unavailable" message."""
    from mediahub.web import web as _web
    fake_run = {
        "profile_display": "Test Club",
        "meet": {"name": "Test Meet"},
        "recognition_report": {
            "ranked_achievements": [{
                "achievement": {
                    "swim_id": "abc123",
                    "swimmer_name": "Jane Doe",
                    "event": "100 Free",
                    "time": "1:02.34",
                    "pb": True,
                    "place": 1,
                    "type": "PB",
                    "headline": "First place",
                },
            }],
        },
    }
    monkeypatch.setattr(_web, "_load_run", lambda rid: fake_run)
    c = app.test_client()
    r = c.post("/api/runs/test_run/swim/abc123/caption?tone=ai")
    assert r.status_code == 200
    j = r.get_json()
    assert j["tone"] == "ai"
    assert j["live"] is False
    assert j["error"] == "no_key"
    assert j["caption"] == ""
    # The new copy steers the user to their administrator, NOT a settings page.
    assert "administrator" in j["message"].lower()
    assert "Settings" not in j["message"]


# ---------------------------------------------------------------------------
# env-var key resolution still works through the new chain
# ---------------------------------------------------------------------------

def test_env_anthropic_key_picked_up(app, monkeypatch):
    """The LLM module reads ANTHROPIC_API_KEY from env directly."""
    from mediahub.media_ai import llm as _llm
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake-env-key-abcdef12345")
    assert _llm._resolve_anthropic_key() == "sk-ant-fake-env-key-abcdef12345"
    assert _llm._has_anthropic_key() is True
    assert _llm.is_available() is True


def test_env_gemini_key_picked_up(app, monkeypatch):
    """The LLM module reads GEMINI_API_KEY (or GOOGLE_API_KEY) from env."""
    from mediahub.media_ai import llm as _llm
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-fake-env-key-xyz")
    assert _llm._resolve_gemini_key() == "AIza-fake-env-key-xyz"
    assert _llm._has_gemini_key() is True
    assert _llm.is_available() is True


def test_no_env_no_provider(app):
    """With no env keys and an empty disk store, is_available is False."""
    from mediahub.media_ai import llm as _llm
    assert _llm._has_anthropic_key() is False
    assert _llm._has_gemini_key() is False
    assert _llm.is_available() is False
    assert _llm.active_provider() == "heuristic"
