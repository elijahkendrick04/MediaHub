"""H-21 — the board's "New idea" needs a visible Add button.

The Ideas column input submitted only via an Enter keydown; nothing on screen
showed how to confirm, and clicking away lost the typed idea silently (empty
submits also returned silently). There is now an Add button beside the input, a
"press Enter" hint, and an explicit status message when the title is empty.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def board_html(tmp_path, monkeypatch):
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
    return c.get("/plan/board").get_data(as_text=True)


def test_add_button_present(board_html):
    assert 'class="mh-bd-add-btn"' in board_html
    assert 'onclick="mhBoardAdd(this)"' in board_html
    assert ">Add</button>" in board_html
    assert "or press Enter to add" in board_html


def test_enter_still_works(board_html):
    assert "if(event.key==='Enter')mhBoardAdd(this)" in board_html


def test_empty_title_surfaces_status(board_html):
    # The empty-input case now tells the user, rather than returning silently.
    assert "Type an idea first, then press Add." in board_html
