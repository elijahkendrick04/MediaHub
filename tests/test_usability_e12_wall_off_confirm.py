"""E-12 — "Switch off & revoke the link" must be confirmed, spelling out the cost.

Disabling the public wall clears public_wall_token, so the shared URL, the
website embed, the RSS/JSON feeds and any printed QR codes all die
permanently — re-enabling mints a NEW token. The disable form had no
confirmation at all. It now routes through mhWallOffConfirm (styled
MH.confirm where loaded, native confirm fallback) that says exactly that.
Token semantics are unchanged — this is a confirm-only fix.
"""

from __future__ import annotations

import pathlib

import pytest

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


# --- Source-level pins (the confirm is client-side JS in the template) -------


def test_disable_form_routes_through_the_confirm():
    assert 'onsubmit="return mhWallOffConfirm(this)"' in _SRC
    assert "function mhWallOffConfirm(f)" in _SRC


def test_confirm_spells_out_the_cost_and_the_new_link():
    assert (
        "Your public link, website embed, feeds and any QR codes will stop working."
        in _SRC
    )
    assert "Switching back on creates a DIFFERENT link." in _SRC


def test_confirm_prefers_styled_modal_with_native_fallback():
    i = _SRC.index("function mhWallOffConfirm(f)")
    block = _SRC[i : i + 900]
    assert "if (window.MH && MH.confirm)" in block
    assert "return confirm(" in block


# --- Behavioural: the page carries the script; disable still works ----------


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


def _pin_org(client, profile_id="sharks"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=profile_id, display_name="Sharks"))
    with client.session_transaction() as sess:
        sess["active_profile_id"] = profile_id
        sess["login_seen_at"] = 2**62


def test_enabled_wall_page_ships_the_confirm_script(app):
    client = app.test_client()
    _pin_org(client)
    client.post("/public-wall/update", data={"action": "enable"})
    html = client.get("/public-wall").get_data(as_text=True)
    assert "mhWallOffConfirm" in html
    assert "Switching back on creates a DIFFERENT link." in html


def test_disable_still_revokes_and_reenable_mints_new_token(app):
    """Token semantics untouched: disable clears the token, re-enable mints a
    different one (the exact behaviour the confirm warns about)."""
    from mediahub.web.club_profile import load_profile

    client = app.test_client()
    _pin_org(client)
    client.post("/public-wall/update", data={"action": "enable"})
    first = load_profile("sharks").public_wall_token
    assert first

    r = client.post("/public-wall/update", data={"action": "disable"})
    assert r.status_code == 302
    prof = load_profile("sharks")
    assert prof.public_wall_enabled is False
    assert prof.public_wall_token == ""

    client.post("/public-wall/update", data={"action": "enable"})
    second = load_profile("sharks").public_wall_token
    assert second and second != first
