"""H-22 — the slide-remote landing must validate the 6-char code before it
navigates.

Connect fired ``location.href='/remote/'+value`` with no client-side check, so a
partial or mistyped code navigated to /remote/<code>, failed the lookup, and
burned a per-IP failure attempt — which at a venue behind one NAT erodes the
shared budget. Connect is now disabled until exactly six characters from the
unambiguous code alphabet are entered, and Connect re-validates before it moves.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def remote_html(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app.test_client().get("/remote").get_data(as_text=True)


def test_connect_disabled_until_valid(remote_html):
    # Button ships disabled and is validated by rgClean/rgGo.
    assert 'id="rgo"' in remote_html
    assert "disabled" in remote_html
    assert "function rgClean()" in remote_html
    assert "function rgGo()" in remote_html


def test_validation_matches_the_code_alphabet(remote_html):
    # The regex is the presenter code alphabet (no 0/O/1/I/L), length 6.
    assert "/^[A-HJKMNP-Z2-9]{6}$/" in remote_html


def test_old_unguarded_connect_gone(remote_html):
    # The bare "navigate on click, no check" handler must be gone.
    assert "location.href='/remote/'+document.getElementById('code').value.toUpperCase()" not in (
        remote_html
    )


def test_alphabet_stays_in_sync_with_presenter():
    # If the presenter alphabet ever changes, this fails so the regex is updated.
    from mediahub.documents import presenter

    importlib.reload(presenter)
    assert set(presenter._CODE_ALPHABET) == set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
    assert presenter._CODE_LEN == 6
