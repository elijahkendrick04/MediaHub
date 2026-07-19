"""Regression tests for deep-review batch 2 (security cluster).

Covers:
  #33  ai_core sends the Gemini key in the x-goog-api-key header, not the URL
  #102 consent.effective_policy fails CLOSED on a DB error
  #25  UserStore.set_password bumps session_epoch (revokes old cookies)
  #23  the /drafts autographic view escapes the reflected `photo` param
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# --------------------------------------------------------------------------- #
# #33 — Gemini key travels in the header, never the URL query string
# --------------------------------------------------------------------------- #
def test_ai_core_gemini_key_in_header_not_url(monkeypatch):
    import requests

    from mediahub.ai_core import llm

    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-key-xyz")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    captured = {}

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    def _fake_post(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return _Resp()

    monkeypatch.setattr(requests, "post", _fake_post)

    out = llm._ask_gemini("system prompt", "user prompt", 100)
    assert out == "ok"

    # The key must NOT ride in the URL or in a `params={"key": ...}` query.
    assert "test-secret-key-xyz" not in captured["url"]
    assert "key" not in (captured["kwargs"].get("params") or {})
    # It must be in the header instead.
    assert captured["kwargs"]["headers"].get("x-goog-api-key") == "test-secret-key-xyz"


# --------------------------------------------------------------------------- #
# #102 — consent policy fails CLOSED (blocked) on a DB error
# --------------------------------------------------------------------------- #
def test_effective_policy_fails_closed_on_db_error(monkeypatch, tmp_path):
    from mediahub.safeguarding import consent

    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def _boom(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(consent, "regime_active", _boom)

    policy = consent.effective_policy("club-x", "Jamie Rivers")
    assert policy.blocked is True, "a consent-lookup DB error must block, not permit"
    assert policy.name_ok is False and policy.photo_ok is False


# --------------------------------------------------------------------------- #
# #25 — a password reset revokes outstanding sessions (bumps the epoch)
# --------------------------------------------------------------------------- #
def test_set_password_bumps_session_epoch(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    from mediahub.web import auth

    store = auth.UserStore()
    user = store.create("owner@club.org", "originalpass123")
    epoch_before = int(user.session_epoch or 0)

    updated = store.set_password("owner@club.org", "brandnewpass456")
    assert updated is not None
    assert int(updated.session_epoch or 0) == epoch_before + 1, (
        "set_password must bump session_epoch so old cookies are revoked"
    )
    # The bump is durable, not just on the returned object.
    reread = store._read_all().get("owner@club.org")
    assert int(reread.session_epoch or 0) == epoch_before + 1


# --------------------------------------------------------------------------- #
# #23 — reflected `photo` param cannot break out of the inline <script>
# --------------------------------------------------------------------------- #
@pytest.fixture
def stub_app(app, tmp_path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    return app, tmp_path


def test_drafts_autographic_photo_param_is_escaped(stub_app, monkeypatch):
    app, tmp_path = stub_app

    import mediahub.club_platform.stubs as _stubs

    def _stub_generate(*_a, **_k):
        return {
            "cards": [
                {
                    "platform": "Instagram",
                    "caption": "Test",
                    "hashtags": ["t"],
                    "confidence": 0.7,
                    "notes": "",
                }
            ]
        }

    monkeypatch.setattr(_stubs, "_generate_cards_via_llm", _stub_generate)

    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        c.post(
            "/weekend-preview",
            data={"meet_name": "Meet", "athletes": "Alex — 50 Free"},
            content_type="multipart/form-data",
        )
        packs = list((tmp_path / "stub_packs").glob("*.json"))
        assert packs, "no stub pack was persisted"
        pack_id = json.loads(packs[0].read_text())["pack_id"]

        payload = "</script><script>alert(1)</script>"
        resp = c.get(f"/drafts/{pack_id}?autographic=1&photo={payload}")

    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    # The injected <script> must not appear literally (breakout neutralised)...
    assert "<script>alert(1)" not in body
    # ...and the reflected value survives only in <-escaped form inside the
    # inline script, so the HTML parser never sees a real < from the photo param.
    assert "u003cscript" in body, "photo param was not escaped for the <script> context"
