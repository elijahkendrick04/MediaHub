"""J-10 — the two placeholder Settings tiles must read as "Coming soon" before
the click.

"Auto scheduling" and "Autonomy" occupied two full tiles with the same weight
and the same "Open →" CTA as working features; clicking either cost a page load
to reach a single placeholder card. Both tiles now carry a visible "Coming soon"
badge and a muted CTA, while the other tiles still say "Open".
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def settings_html(tmp_path, monkeypatch):
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
    return c.get("/settings").get_data(as_text=True)


def test_coming_soon_tiles_badged(settings_html):
    assert '<span class="mh-template-soon-badge">Coming soon</span>' in settings_html
    # Exactly the two placeholder tiles get the badge markup (the CSS selector,
    # inlined on the page, is excluded by matching the class attribute form).
    assert settings_html.count('class="mh-template-soon-badge"') == 2
    # …and both carry the muted tile class.
    assert 'class="mh-template mh-glow-border mh-template-soon"' in settings_html


def test_working_tiles_still_open(settings_html):
    # The grid still has "Open" CTAs on the working tiles.
    assert ">Open</span>" in settings_html
    # …and the two placeholders show "Coming soon" as their CTA.
    assert ">Coming soon</span>" in settings_html
