"""Settings page + caption-no-key behaviour.

Operator credentials (AI keys, the scheduler token) remain env-var only —
they have NO user-facing configuration surface. /settings now renders
a consolidated Operations page (Activity, Status, Privacy, Deployment
status) but exposes zero credential editing.

This test file pins what's left:

  • /settings renders a real page (consolidated Operations)
  • /api/settings/llm-status remains a read-only status endpoint
  • The caption endpoint with no LLM key returns
    {live: false, error: "no_key", message: <admin-facing copy>}
  • API error messages must NOT direct users to "configure in Settings"
    (still true — the Settings page has no credential controls)
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
# /settings renders the consolidated Operations page
# ---------------------------------------------------------------------------

def test_settings_renders_card_grid_landing(app):
    """Settings renders a card grid (like Create): one tile per heading,
    each opening its own detail page. It is the topnav target and no
    longer a 302-to-home relic."""
    c = app.test_client()
    r = c.get("/settings", follow_redirects=False)
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # The heading cards are present on the landing grid.
    assert "Activity" in body
    assert "Auto scheduling" in body
    assert "Autonomy" in body
    assert "Privacy &amp; data" in body or "Privacy & data" in body
    assert "System status" in body
    # Styled like the Create tiles, and carries the Settings active state.
    assert "mh-template" in body
    assert "Settings" in body


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
    # The orphaned settings_url field must not be emitted — /settings is gone.
    assert "settings_url" not in j


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


# ---------------------------------------------------------------------------
# Rendered-page invariant — the Settings topnav link is the only
# /settings reference allowed. The error-message paths that used to
# surface a dead "Open Settings" / "Add an API key" / the scheduler-redirect
# anchor must still be gone — those flows steer users to their
# administrator instead, because /settings has no credential surface.
# ---------------------------------------------------------------------------

def test_rendered_page_has_only_topnav_settings_link(app):
    """The Settings navigation anchors exist (the desktop topnav link, the
    mobile bottom-tab link, and the UI 1.28 keyboard-shortcuts overlay's
    'Go to Settings' row — all three plain navigation, all to the consolidated
    Operations page). Beyond those, no JS error message or the scheduler flow
    is allowed to redirect to /settings — those paths still need to steer the
    user to their administrator, since the Settings page has no credential
    controls."""
    import re
    c = app.test_client()
    r = c.get("/", follow_redirects=True)
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # The Settings anchors are navigation only: the desktop topnav link, the
    # mobile bottom-tab link (added in the mobile-nav pass; display:none on
    # desktop but always in the DOM), and the global shortcuts-overlay 'g s'
    # row (UI 1.28 — a plain url_for() link that doubles as a click menu).
    settings_anchors = re.findall(
        r"""<a[^>]+href\s*=\s*["']/settings["'][^>]*>""", html,
    )
    assert len(settings_anchors) == 3, (
        f"expected the topnav + mobile-bottomnav + shortcuts-overlay /settings "
        f"anchors, found {len(settings_anchors)}"
    )
    # Both must be plain navigation anchors, not credential-flow links.
    assert all("aria-label" in a or 'class="' in a for a in settings_anchors)
    # No window.location redirect to /settings (the old schedule-modal fallback).
    assert not re.search(r"""window\.location\.href\s*=\s*['"]/settings['"]""", html)
    assert "API_BASE + '/settings'" not in html
    # No JSON-consumer fallback that hardcoded '/settings' as a link.
    assert "settings_url || " not in html
    assert "j.settings_url" not in html
    # The replacement copy is present in the shell JS.
    assert "Contact your administrator" in html


def test_caption_endpoint_llm_unavailable_error_steers_to_administrator(app, monkeypatch):
    """Pins the _ClaudeUE / llm_unavailable error branch (web.py ~4736).

    When the LLM provider is configured (is_available -> True) but the
    generation call itself raises ClaudeUnavailableError (transient
    upstream failure, bad key, rate-limit, etc.), the caption endpoint
    must surface administrator-facing copy — NOT a now-deleted Settings
    page reference."""
    from mediahub.web import web as _web
    from mediahub.web import ai_caption as _ai_caption

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
    # Force is_available -> True so we bypass the no_key branch.
    from mediahub.media_ai import llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: True)
    # Force the live generator to raise ClaudeUnavailableError so we land
    # in the _ClaudeUE branch at web.py:4727.
    def _raise(*a, **kw):
        raise _ai_caption.ClaudeUnavailableError("upstream 503")
    monkeypatch.setattr(_ai_caption, "generate_caption_for_tone", _raise)

    c = app.test_client()
    r = c.post("/api/runs/test_run/swim/abc123/caption?tone=ai&n_variants=1")
    assert r.status_code == 200
    j = r.get_json()
    assert j["tone"] == "ai"
    assert j["caption"] == ""
    # Phase 1.5: ClaudeUnavailableError("upstream 503") is now classed
    # as a transient failure (not "no key configured"), so the response
    # tells the user to retry rather than contact their administrator.
    # `live` stays True because the provider IS reachable in principle.
    assert j["error"] == "transient"
    assert j["live"] is True
    # The retry copy.
    assert ("retry" in j["message"].lower()
            or "try again" in j["message"].lower()
            or "few seconds" in j["message"].lower())
    # No reference to the deleted Settings page either way.
    assert "Settings" not in j["message"]
    assert "in Settings" not in j["message"]
    assert "Gemini API key" not in j["message"]
    assert "Anthropic key" not in j["message"]


def test_caption_endpoint_no_key_steers_to_administrator(app, monkeypatch):
    """When the LLM provider raises with terminal wording ("not
    configured" / "unavailable on this deployment"), the error class
    is no_key and the user is steered to their administrator. This is
    the complement to the transient test above."""
    from mediahub.web import web as _web
    from mediahub.web import ai_caption as _ai_caption

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
                    "pb": True, "place": 1, "type": "PB",
                    "headline": "First place",
                },
            }],
        },
    }
    monkeypatch.setattr(_web, "_load_run", lambda rid: fake_run)
    from mediahub.media_ai import llm as _llm
    monkeypatch.setattr(_llm, "is_available", lambda: True)
    def _raise(*a, **kw):
        raise _ai_caption.ClaudeUnavailableError(
            "AI features are unavailable on this deployment. No provider configured."
        )
    monkeypatch.setattr(_ai_caption, "generate_caption_for_tone", _raise)

    c = app.test_client()
    r = c.post("/api/runs/test_run/swim/abc123/caption?tone=ai&n_variants=1")
    assert r.status_code == 200
    j = r.get_json()
    assert j["error"] == "no_key"
    assert j["live"] is False
    assert "administrator" in j["message"].lower()


def test_no_api_key_message_does_not_steer_to_settings_page(app, monkeypatch):
    """When the caption endpoint returns no_key, the JSON payload must
    not contain a settings_url or any 'in Settings' wording. The user-
    visible affordance is admin contact, not a settings page."""
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
    j = r.get_json()
    assert j["error"] == "no_key"
    # No settings_url field — /settings is gone.
    assert "settings_url" not in j
    # No "in Settings" stale wording in the message.
    assert "in Settings" not in j["message"]
    assert "settings page" not in j["message"].lower()
