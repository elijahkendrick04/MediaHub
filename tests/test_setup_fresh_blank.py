"""Regression — "Create new organisation" must open a blank setup form.

Bug: the create-new link pointed at /organisation/setup, which pre-fills
every field (name, website, socials, logo, guidelines) and the
"What MediaHub learned" preview from the *currently active* org. A user
creating a second club saw the first club's data on screen and could build
a new org on top of inherited assets.

Fix: the link carries ?fresh=1, and the setup route renders a blank form
(and no preview) when fresh, without touching the active session org.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _make_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles", "data"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="existing-club",
            display_name="Existing Swim Club",
            brand_voice_summary="Bold and proud.",
            brand_source_url="https://existing-club.example",
            brand_primary="#3060d8",
            brand_palette_extracted={
                "primary": "#3060d8",
                "secondary": "#1b2a55",
                "accent": "#77a7ff",
            },
            brand_guidelines_filename="existing_brand.md",
            brand_guidelines={"voice_summary": "Bold and proud."},
        )
    )
    a = wm.create_app()
    a.config["TESTING"] = True
    return a


def _client_with_active(app):
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "existing-club"
    return c


def test_default_setup_prefills_active_org(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    c = _client_with_active(app)
    body = c.get("/organisation/setup").data.decode("utf-8", errors="ignore")
    # Sanity: without ?fresh the active org IS pre-filled / previewed.
    assert 'value="Existing Swim Club"' in body
    assert 'value="https://existing-club.example"' in body


def test_fresh_setup_is_blank(tmp_path, monkeypatch):
    app = _make_app(tmp_path, monkeypatch)
    c = _client_with_active(app)
    body = c.get("/organisation/setup?fresh=1").data.decode("utf-8", errors="ignore")
    # The active org's data must NOT pre-fill the blank "create new" form.
    # (The global nav still shows the active org chip — that's correct, the
    # user is still signed in — so we assert on the form field values.)
    assert 'value="Existing Swim Club"' not in body, "fresh form leaked the active org name"
    assert (
        'value="https://existing-club.example"' not in body
    ), "fresh form leaked the active org website"
    assert "existing_brand.md" not in body, "fresh form leaked the active org's guidelines file"
    assert "What MediaHub learned" not in body, "fresh setup showed the active org's preview"
    # The form itself is still there to fill in.
    assert 'name="display_name"' in body


def test_create_new_link_uses_fresh(tmp_path, monkeypatch):
    """The sign-in page's create-new card must point at the blank form."""
    app = _make_app(tmp_path, monkeypatch)
    c = app.test_client()  # signed out — sign-in page lists profiles
    body = c.get("/sign-in").data.decode("utf-8", errors="ignore")
    assert "Create new organisation" in body
    assert "fresh=1" in body, "create-new link does not request a blank (fresh) form"
