"""I-6 & I-8 — the notifications popover and the media-library Convert menu need
keyboard/screen-reader focus handling.

I-6: opening the notifications bell announced a "dialog" but left focus on the
bell (Tab walked backwards into the nav). Focus now moves into the panel on
open; Escape already closed it and restored focus.

I-8: the per-row Convert menu was an unlabelled injected div — no role/aria on
the menu, no aria-haspopup/expanded on the trigger, no Escape, no focus moved
in, and errors shown only by rewriting a tiny label. It now has role=menu,
menuitems, aria-haspopup/expanded, Escape-to-close, focus-in, and MH.toast
errors.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def client(app):
    """Isolated app via the shared conftest fixtures (no ``importlib.reload``)
    with a saved, active ``club-a`` profile — #130 fixture-sprawl migration."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "club-a"
        yield c


def test_notif_popover_moves_focus_in(client):
    html = client.get("/").get_data(as_text=True)
    # setOpen now focuses the first control in the panel on open.
    assert "panel.querySelector('button, [href], [tabindex]:not([tabindex=\"-1\"])')" in html
    # Escape already restores focus to the bell.
    assert "e.key === 'Escape' && open" in html


def test_convert_menu_is_keyboard_accessible(client):
    html = client.get("/media-library").get_data(as_text=True)
    # Trigger advertises the popup.
    assert 'aria-haspopup="menu" aria-expanded="false"' in html
    # The injected menu + items carry roles, focus-in, Escape, and toast errors.
    assert "menu.setAttribute('role', 'menu')" in html
    assert "b.setAttribute('role', 'menuitem')" in html
    assert "ev.key === 'Escape' && activeTrigger" in html
    assert "MH.toast(msg, 'error'" in html
