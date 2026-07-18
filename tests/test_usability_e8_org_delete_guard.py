"""E-8 — deleting an organisation from the sign-in picker must be plain-spoken
about what's lost, and a non-owner who clicks delete must be told why nothing
happened (it used to bounce silently).
"""

from __future__ import annotations

import pytest

from tests._helpers import web_surface_src

# The sign_in_delete handler lives on the carved web surface (routes_auth.py
# since the #15 carve), so scan the whole surface, not one file.
_SRC = web_surface_src()


@pytest.fixture
def client(web_module, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Otters SC"))
    app = web_module.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app.test_client()


def test_delete_confirm_is_plain_and_not_jargon(client):
    html = client.get("/sign-in").get_data(as_text=True)
    # The old jargon ("Its runs stay on disk but it disappears from this picker")
    # is gone; the new copy is plain and states permanence + what's kept.
    assert "disappears from this picker" not in html
    assert "Remove &quot;Otters SC&quot; from this sign-in list permanently?" in html
    assert "Your processed results are kept" in html


def test_non_owner_delete_is_wired_to_a_flash_not_a_silent_bounce():
    # The non-owner branch of sign_in_delete flashes an explanation.
    assert (
        'session["sign_in_error"] = "Only the workspace owner can delete this organisation."'
        in _SRC
    )


def test_flash_message_renders_on_the_picker(client):
    # The sign-in picker surfaces a flashed error (the channel the non-owner
    # bounce now uses), so the member sees the reason.
    with client.session_transaction() as s:
        s["sign_in_error"] = "Only the workspace owner can delete this organisation."
    html = client.get("/sign-in").get_data(as_text=True)
    assert "Only the workspace owner can delete this organisation." in html
