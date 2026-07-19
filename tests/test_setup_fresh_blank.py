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


def _make_app(web_module, tmp_path):
    # DATA_DIR / RUNS_DIR / UPLOADS_DIR / profiles-dir isolation (all under this
    # test's tmp_path) plus the one-time web.py import come from the ``web_module``
    # fixture (which pulls in ``_isolate_data_dir``) — this test just needs one
    # extra 'data' subdir and a pre-seeded active org.
    wm = web_module
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)

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


def test_default_setup_prefills_active_org(web_module, tmp_path):
    app = _make_app(web_module, tmp_path)
    c = _client_with_active(app)
    body = c.get("/organisation/setup").data.decode("utf-8", errors="ignore")
    # Sanity: without ?fresh the active org IS pre-filled / previewed.
    assert 'value="Existing Swim Club"' in body
    assert 'value="https://existing-club.example"' in body


def test_fresh_setup_is_blank(web_module, tmp_path):
    app = _make_app(web_module, tmp_path)
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


def test_create_new_link_uses_fresh(web_module, tmp_path):
    """The sign-in page's create-new card must point at the blank form."""
    app = _make_app(web_module, tmp_path)
    c = app.test_client()  # signed out — sign-in page lists profiles
    body = c.get("/sign-in").data.decode("utf-8", errors="ignore")
    assert "Create new organisation" in body
    assert "fresh=1" in body, "create-new link does not request a blank (fresh) form"
