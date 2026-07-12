"""tests/test_caption_platform_and_persist.py — follow-up caption UX features.

Covers the three review/content-builder caption improvements:

  1. Per-platform variants route (api_caption_platforms) — adapt one caption
     into feed / story / X / LinkedIn via generate_platform_variants, with the
     same access + honest-no-key handling as the assist route.
  2. The multi-variant picker is reachable — the "More options" control fetches
     several variants (the tone panel JS threads n_variants through).
  3. The approve-without-inspector persistence footgun — the tone panel now has
     a Save button + auto-save helpers that persist to the same headline slots
     the inspector and pack build use.

Route tests use the Flask test client with all AI mocked; the UI-wiring tests
assert the server-rendered toolbar + shared JS carry the new controls.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _fake_run():
    return {
        "run_id": "r1",
        "profile_id": "",
        "profile_display": "City SC",
        "meet": {"name": "County Champs"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": "s1",
                        "swimmer_name": "Alice Smith",
                        "event": "100m Freestyle",
                        "time": "57.10",
                        "headline": "Alice set a PB",
                    }
                }
            ]
        },
    }


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app.test_client()


# ---------------------------------------------------------------------------
# 1. Per-platform variants route
# ---------------------------------------------------------------------------


class TestPlatformVariantsRoute:
    def test_success_returns_all_platforms(self, client, monkeypatch):
        monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.web.ai_caption.generate_platform_variants",
            lambda *a, **k: {
                "feed": "Feed variant.",
                "story": "Story variant.",
                "x": "X variant.",
                "linkedin": "LinkedIn variant.",
            },
        )
        r = client.post(
            "/api/runs/r1/swim/s1/caption/platforms",
            json={"caption": "Alice Smith swam a 57.10 PB in the 100m free."},
        )
        assert r.status_code == 200
        j = r.get_json()
        assert j["live"] is True
        assert set(j["variants"].keys()) == {"feed", "story", "x", "linkedin"}

    def test_empty_caption_rejected(self, client, monkeypatch):
        monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
        r = client.post("/api/runs/r1/swim/s1/caption/platforms", json={"caption": "   "})
        assert r.status_code == 400
        assert r.get_json()["error"] == "empty_caption"

    def test_no_key_is_honest(self, client, monkeypatch):
        monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: False)
        r = client.post("/api/runs/r1/swim/s1/caption/platforms", json={"caption": "hi there"})
        assert r.status_code == 200
        j = r.get_json()
        assert j["error"] == "no_key" and j["variants"] == {}

    def test_provider_unavailable_is_no_key(self, client, monkeypatch):
        monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        from mediahub.web.ai_caption import ClaudeUnavailableError

        def boom(*a, **k):
            raise ClaudeUnavailableError("no key")

        monkeypatch.setattr("mediahub.web.ai_caption.generate_platform_variants", boom)
        r = client.post("/api/runs/r1/swim/s1/caption/platforms", json={"caption": "hi there"})
        assert r.status_code == 200
        assert r.get_json()["error"] == "no_key"

    def test_transient_when_provider_returns_nothing(self, client, monkeypatch):
        monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        monkeypatch.setattr(
            "mediahub.web.ai_caption.generate_platform_variants",
            lambda *a, **k: {"feed": "   ", "story": ""},
        )
        r = client.post("/api/runs/r1/swim/s1/caption/platforms", json={"caption": "hi there"})
        assert r.status_code == 200
        j = r.get_json()
        assert j["error"] == "transient" and j["variants"] == {}

    def test_run_not_found(self, client, monkeypatch):
        monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: None)
        r = client.post("/api/runs/missing/swim/s1/caption/platforms", json={"caption": "x"})
        assert r.status_code == 404

    def test_idor_blocked(self, client, monkeypatch):
        monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
        monkeypatch.setattr("mediahub.web.web._can_access_run", lambda *a, **k: False)
        r = client.post("/api/runs/r1/swim/s1/caption/platforms", json={"caption": "x"})
        assert r.status_code == 404

    def test_oversized_caption_capped(self, client, monkeypatch):
        monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        captured = {}

        def fake_gen(base, **k):
            captured["base"] = base
            return {"feed": "F"}

        monkeypatch.setattr("mediahub.web.ai_caption.generate_platform_variants", fake_gen)
        r = client.post(
            "/api/runs/r1/swim/s1/caption/platforms", json={"caption": "A" * 100_000}
        )
        assert r.status_code == 200
        assert len(captured["base"]) <= 4000

    def test_platform_subset_forwarded(self, client, monkeypatch):
        monkeypatch.setattr("mediahub.web.web._load_run", lambda rid: _fake_run())
        monkeypatch.setattr("mediahub.media_ai.llm.is_available", lambda: True)
        captured = {}

        def fake_gen(base, **k):
            captured["platforms"] = k.get("platforms")
            return {"feed": "F"}

        monkeypatch.setattr("mediahub.web.ai_caption.generate_platform_variants", fake_gen)
        r = client.post(
            "/api/runs/r1/swim/s1/caption/platforms",
            json={"caption": "hi", "platforms": ["feed", "x"]},
        )
        assert r.status_code == 200
        assert captured["platforms"] == ["feed", "x"]


# ---------------------------------------------------------------------------
# 2 + 3. Toolbar + shared JS carry the new controls
# ---------------------------------------------------------------------------


class TestToolbarWiring:
    def test_toolbar_has_new_caption_controls(self, client):
        from mediahub.web.web import _render_card_creative_toolbar

        with client.application.test_request_context("/"):
            html = _render_card_creative_toolbar("run1", "swim-1")
        for needle in (
            "More options",
            "Platform variants",
            "Save caption",
            'class="caption-save-status"',
            'class="platform-variants-out"',
            "moreCaptionOptions(this,",
            "platformVariants(this,",
            "saveActiveCaption(this,",
        ):
            assert needle in html, needle

    def test_creative_js_has_persist_and_platform_helpers(self, client):
        from mediahub.web.web import _card_creative_js

        with client.application.test_request_context("/"):
            js = _card_creative_js()
        for needle in (
            "function _persistCaption",
            "function saveActiveCaption",
            "function moreCaptionOptions",
            "function platformVariants",
            "function _setSaveStatus",
            # the picker now threads n_variants through the fetch URL
            "n_variants=' + nv",
            # regenerate persists (WYSIWYG on approval)
            "cardId, 1, true)",
            # more-options asks for several variants so the picker renders
            "cardId, 3, false)",
            # persistence targets the same slots the inspector + pack build use
            "warm-club_headline",
        ):
            assert needle in js, needle
