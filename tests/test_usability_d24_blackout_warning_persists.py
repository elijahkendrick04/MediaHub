"""D-24 — the blackout-date warning must not flash for 1.2s then be wiped by the
reload.

Dropping a draft on a blackout date is the soft gate's one moment to warn, but
the warning rendered in 12.5px status text for exactly 1200ms before the page
reloaded and erased it. The warning is now persisted across the reload and shown
as a dismissible toast.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def page_html(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c.get("/plan/calendar").get_data(as_text=True)


def test_warning_persisted_across_reload(page_html):
    assert "sessionStorage.setItem('mhCalWarn'" in page_html
    assert "sessionStorage.getItem('mhCalWarn')" in page_html
    assert "MH.toast(w, 'error', 8000)" in page_html


def test_old_flash_then_reload_pattern_gone(page_html):
    # The 1.2s flash-then-reload that erased the warning is gone.
    assert "window.location.reload(); }}, 1200)" not in page_html
    assert "reload(); }, 1200)" not in page_html
