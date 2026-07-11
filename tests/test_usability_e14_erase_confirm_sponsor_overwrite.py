"""E-14 — the athlete erase gets a scoped, danger-styled confirm; a same-named
sponsor add stops silently overwriting.

"Erase an athlete" wipes a person from every run/render/cache/memory/log
irreversibly but was a `btn secondary` behind a generic confirm(). It is now a
`btn danger` behind an MH.confirm (native-confirm fallback) that enumerates
the scope plainly. `sponsors_add` de-duped by sponsor_id and silently replaced
an existing entry; the replace semantics stay but the user now gets a flash
toast saying the existing sponsor was updated.
"""

from __future__ import annotations

import pathlib

import pytest

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


# --- Source-level pins (the confirm is client-side JS in the template) -------


def test_generic_erase_confirm_is_gone():
    assert "Erase this athlete from all stored data?" not in _SRC


def test_erase_uses_scoped_mh_confirm_with_fallback():
    # The form routes through the shared intercept…
    assert 'onsubmit="return mhEraseAthleteConfirm(this)"' in _SRC
    assert "function mhEraseAthleteConfirm(f)" in _SRC
    # …which prefers the styled MH.confirm and falls back to native confirm.
    assert "if (window.MH && MH.confirm)" in _SRC
    assert "return confirm(scope);" in _SRC
    # The body enumerates the scope plainly (results, graphics, caches,
    # caption memory, posting logs) and says it cannot be undone.
    assert (
        "results, rendered graphics, caches, caption memory and posting logs"
        in _SRC
    )
    assert "confirmText: 'Erase athlete'" in _SRC


def test_erase_button_is_danger_styled():
    # The erase submit is danger-styled (CSS-var-driven .btn.danger), not a
    # generic secondary button.
    assert (
        '<button class="btn danger" type="submit">Erase athlete</button>' in _SRC
    )


# --- Behavioural: sponsor same-name add flashes instead of silent replace ----


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


def test_same_name_sponsor_add_replaces_and_tells_the_user(app):
    client = app.test_client()
    _pin_org(client)
    r1 = client.post(
        "/sponsors/add",
        data={"name": "Acme Sports", "tier": "gold"},
        follow_redirects=True,
    )
    assert r1.status_code == 200
    # First add: no "updated existing" message.
    assert "Updated existing sponsor" not in r1.get_data(as_text=True)

    r2 = client.post(
        "/sponsors/add",
        data={"name": "Acme Sports", "tier": "silver"},
        follow_redirects=True,
    )
    assert r2.status_code == 200
    body = r2.get_data(as_text=True)
    assert "Updated existing sponsor" in body
    assert "Acme Sports" in body

    # Replace semantics kept: still exactly one entry, carrying the new tier.
    from mediahub.web.club_profile import load_profile

    sponsors = [
        s
        for s in (load_profile("sharks").sponsors or [])
        if isinstance(s, dict) and s.get("name") == "Acme Sports"
    ]
    assert len(sponsors) == 1
    assert sponsors[0]["tier"] == "silver"


def test_distinct_sponsor_names_never_flash_updated(app):
    client = app.test_client()
    _pin_org(client)
    client.post("/sponsors/add", data={"name": "Acme Sports", "tier": "gold"})
    r = client.post(
        "/sponsors/add",
        data={"name": "Borough Bakery", "tier": "bronze"},
        follow_redirects=True,
    )
    assert "Updated existing sponsor" not in r.get_data(as_text=True)
    from mediahub.web.club_profile import load_profile

    assert len(load_profile("sharks").sponsors or []) == 2
