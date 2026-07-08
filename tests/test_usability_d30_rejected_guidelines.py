"""D-30 — a rejected brand-guidelines upload must not be reported inside a green
"Loaded" box with a raw internal status code.

Uploading a PNG as "brand guidelines" is correctly rejected, but the setup page
rendered the rejection inside the green-tinted "Loaded: <filename>" box with the
raw status ("unsupported_binary: ...") in muted text — a volunteer scanning the
page sees green + "Loaded" and concludes their guide was ingested when it was
not. Failures now get warning styling, "Couldn't read", a plain reason, and no
internal codes.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app


def _profile(app, pid="club-a", **kw):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name="Club A", **kw))


def _client(app, pid="club-a"):
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = pid
    return c


def test_rejected_guidelines_shown_as_failure_not_green_loaded(app_env):
    _profile(
        app_env,
        brand_guidelines_filename="guide.png",
        brand_guidelines_status=(
            "unsupported_binary: 'guide.png' looks like an image / binary file."
        ),
    )
    html = _client(app_env).get("/organisation/setup").get_data(as_text=True)
    # No false success.
    assert "Loaded: guide.png" not in html
    # Honest failure framing.
    assert "Couldn&rsquo;t read: guide.png" in html or "Couldn't read: guide.png" in html
    # The raw internal status code is hidden.
    assert "unsupported_binary" not in html


def test_error_status_guidelines_shown_as_failure(app_env):
    _profile(
        app_env,
        brand_guidelines_filename="notes.docx",
        brand_guidelines_status="error: KeyError('body')",
    )
    html = _client(app_env).get("/organisation/setup").get_data(as_text=True)
    assert "Loaded: notes.docx" not in html
    # No raw exception text leaks; the honest failure framing is shown.
    assert "KeyError" not in html
    assert "Couldn&rsquo;t read: notes.docx" in html or "Couldn't read: notes.docx" in html


def test_successful_guidelines_still_shows_loaded(app_env):
    _profile(
        app_env,
        brand_guidelines_filename="brand.pdf",
        brand_guidelines_status="ok",
        brand_guidelines_extractor="pdf",
        brand_guidelines={"summary": "Bold, warm, community-first."},
    )
    html = _client(app_env).get("/organisation/setup").get_data(as_text=True)
    assert "Loaded: brand.pdf" in html
