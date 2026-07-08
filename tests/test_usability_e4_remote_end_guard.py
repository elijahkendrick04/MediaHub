"""E-4 — the phone remote's "End" must be confirmed and must not strand the room.

The remote showed a big "End" button in the same row and weight as "Blackout",
one fat-finger tap from ending the whole presentation with no confirmation and no
undo. Once ended, the pairing code stopped resolving, so reloading the remote gave
a dead "Code not found". Now: End is deprioritised (danger tint, narrow) and gated
behind a confirm(), and an ended-but-valid code lands on a friendly "Presentation
ended" screen — without burning the shared-NAT failure budget.
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


# --- source-level: the remote template's End affordance ---------------------


def test_end_button_is_confirmed_and_deprioritised():
    # End is gated behind a confirm(), not a bare act('end').
    assert "function endPres()" in _SRC
    assert 'onclick="endPres()"' in _SRC
    assert "End the presentation for everyone?" in _SRC
    # It carries its own de-emphasised danger class (not flex:1 like Blackout).
    assert 'class="end"' in _SRC
    assert ".row .end{flex:0 0 auto" in _SRC
    # The remote can flip to a friendly ended screen in-place.
    assert 'id="rended"' in _SRC
    assert "function showEnded()" in _SRC


# --- unit-level: ended sessions are resolvable when asked --------------------


def test_get_by_pairing_code_include_ended(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.documents import presenter

    importlib.reload(presenter)
    s = presenter.create_session("doc1", 3, owner="club-1")
    code = s.pairing_code
    presenter.apply_action(s.session_id, "end")
    # Default lookup hides an ended session (so a live remote can't drive it)…
    assert presenter.get_by_pairing_code(code) is None
    # …but include_ended resolves it so the UI can say "ended", not "not found".
    ended = presenter.get_by_pairing_code(code, include_ended=True)
    assert ended is not None
    assert ended.ended is True


# --- web-level: the ended remote is a friendly close, not a dead end ---------


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
    app = wm.create_app()
    app.config["TESTING"] = True
    return app.test_client(), tmp_path


def _mk_session(tmp_path):
    from mediahub.documents import presenter

    return presenter.create_session("docE4", 3, owner="club-a")


def test_live_code_renders_remote(client):
    c, tmp = client
    s = _mk_session(tmp)
    html = c.get(f"/remote/{s.pairing_code}").get_data(as_text=True)
    assert "endPres()" in html  # the confirmed End is present on a live remote


def test_ended_code_shows_friendly_screen_not_code_not_found(client):
    c, tmp = client
    from mediahub.documents import presenter

    s = _mk_session(tmp)
    presenter.apply_action(s.session_id, "end")
    html = c.get(f"/remote/{s.pairing_code}").get_data(as_text=True)
    assert "Presentation ended" in html
    assert "Code not found" not in html


def test_ended_remote_action_returns_ok_not_failure(client):
    c, tmp = client
    from mediahub.documents import presenter

    s = _mk_session(tmp)
    presenter.apply_action(s.session_id, "end")
    r = c.post(f"/api/remote/{s.pairing_code}/action", json={"action": "next"})
    # A valid-but-ended code is not a 404 "no_session" (which would count a
    # failed attempt against the shared IP budget); it reports the ended state.
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True
    assert j["state"]["ended"] is True
