"""D-16 — rejected logo uploads must not vanish silently.

When a logo upload was rejected (bad / oversized / corrupt) the handler logged
and `continue`d — nothing stored, and the redirect showed the setup page with
the file simply absent from the grid, no clue why. Rejections are now stashed
and surfaced as a warning list above the grid.
"""

from __future__ import annotations

import importlib
import io

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
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app, wm


def test_stashed_rejections_render_and_clear(app_env):
    app, _wm = app_env
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
        s["logo_rejections"] = [
            {"filename": "crest.bmp", "reason": "unsupported format"},
            {"filename": "banner.png", "reason": "over 50 MB"},
        ]
    html = c.get("/organisation/setup").get_data(as_text=True)
    assert "couldn&rsquo;t be used" in html
    assert "crest.bmp" in html and "unsupported format" in html
    assert "banner.png" in html and "over 50 MB" in html
    # One-shot: a second render doesn't repeat the warning.
    html2 = c.get("/organisation/setup").get_data(as_text=True)
    assert "crest.bmp" not in html2


def test_manual_setup_rejected_logo_is_surfaced(app_env, monkeypatch):
    app, _wm = app_env
    import mediahub.brand.logos as _logos_mod

    def _reject(*a, **k):
        raise ValueError("crest.bmp: unsupported logo format")

    monkeypatch.setattr(_logos_mod, "store_logo", _reject)

    c = app.test_client()
    r = c.post(
        "/organisation/setup/manual",
        data={
            "display_name": "Otters SC",
            "brand_logos": (io.BytesIO(b"\x89PNG-fake-bytes"), "crest.bmp"),
        },
        content_type="multipart/form-data",
    )
    assert r.status_code == 302
    html = c.get("/organisation/setup").get_data(as_text=True)
    assert "couldn&rsquo;t be used" in html
    assert "crest.bmp" in html
    assert "unsupported logo format" in html
