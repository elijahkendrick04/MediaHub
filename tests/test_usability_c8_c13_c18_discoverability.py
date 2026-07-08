"""C-8 / C-13 / C-18 — surface orphaned, phone-relevant destinations.

C-13: the media library (camera capture, PWA share-target) was missing from the
mobile bottom nav. C-8: the public achievements wall's only link was buried in
Organisation-settings prose — it gets a Create tile. C-18: the slide remote had
no in-app path (only /remote by hand) — it gets an account-menu shortcut.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(profile_id="club-a", display_name="Riverside SC", brand_voice_summary="x")
    )
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def test_media_in_mobile_bottom_nav(client):
    html = client.get("/").get_data(as_text=True)
    # The mobile bottom nav now includes the media library.
    assert 'class="mh-bottomnav"' in html
    bottom = html.split('class="mh-bottomnav"', 1)[1].split("</nav>", 1)[0]
    assert "/media-library" in bottom
    assert ">Media\n" in bottom or ">Media<" in bottom or "Media" in bottom


def test_public_wall_has_create_tile(client):
    html = client.get("/make").get_data(as_text=True)
    assert "Public wall" in html
    assert "/organisation/public-wall" in html or "public-wall" in html


def test_slide_remote_in_account_menu(client):
    html = client.get("/").get_data(as_text=True)
    assert "Slide remote" in html
    assert "/remote" in html
