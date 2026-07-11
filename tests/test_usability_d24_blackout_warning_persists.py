"""D-24 — the blackout-date warning must not flash for 1.2s then be wiped.

Dropping a draft on a blackout date is the soft gate's one moment to warn, but
the warning used to render in 12.5px status text for exactly 1200ms before a
full page reload erased it. D-26 then removed the reload from the schedule path
entirely, so the warning no longer needs to survive one: the server's copy now
lands in a dismissible inline banner (#mh-cal-warn) that stays on screen until
the volunteer closes it, and the affected chip carries the blackout flag.
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


def test_warning_lands_in_a_staying_inline_banner(page_html):
    # The banner element ships in the markup, announced to screen readers,
    # with a manual dismiss — nothing else clears it.
    assert 'id="mh-cal-warn"' in page_html
    assert 'role="alert"' in page_html
    assert 'aria-label="Dismiss this warning"' in page_html
    # The schedule handler routes the server's warning copy into the banner.
    assert "mhCalWarnBanner(j.warning)" in page_html
    assert "function mhCalWarnBanner(msg)" in page_html


def test_old_flash_then_reload_pattern_gone(page_html):
    # The 1.2s flash-then-reload that erased the warning is gone — and so is
    # the reload itself, so no sessionStorage carry-over is needed either.
    assert "window.location.reload(); }}, 1200)" not in page_html
    assert "reload(); }, 1200)" not in page_html
    assert "location.reload" not in page_html
    assert "sessionStorage.setItem('mhCalWarn'" not in page_html
