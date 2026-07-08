"""E-1 — high-stakes deletes get a styled confirm + undo, not a bare native one.

Deleting a run, all runs, a collection, a sponsor or a member gave nothing but
the browser's grey OS confirm() (and sponsor/member removes had NO confirm at
all), with no undo anywhere. Now: run-delete and clear-all and collection-delete
route through a styled MH.confirm modal; run-delete holds the actual server
delete for ~8s behind an "Undo" toast (soft delete); sponsor and member removes
carry a confirm.
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_mh_confirm_and_toast_action_exist():
    assert "MH.confirm = function" in _SRC
    # MH.toast grew an onClick callback action (for Undo), alongside href links.
    assert "action.onClick" in _SRC


def test_run_delete_has_undo_soft_delete():
    # Deferred commit + Undo toast + beforeunload flush via sendBeacon.
    assert "MH.toast('Meet deleted', 'success', 8000, { text:'Undo'" in _SRC
    assert "navigator.sendBeacon(form.action" in _SRC
    assert "setTimeout(commit, 8000)" in _SRC
    # The initial confirm is the styled modal, not the native one.
    assert "Delete this meet’s results?" in _SRC


def test_undo_restore_guards_a_detached_anchor():
    # Pre-merge review: undoing one delete after the following row was also
    # deleted must not throw on insertBefore(row, detachedAnchor) — the anchor is
    # only reused when still a child of parent, and the re-insert is try/caught.
    assert "anchor.parentNode === parent" in _SRC
    assert "parent.appendChild(row)" in _SRC


def test_clear_all_and_collection_use_styled_confirm():
    assert "MH.confirm({ title: 'Clear all meets?'" in _SRC
    assert "MH.confirm({title:'Delete this collection?'" in _SRC


def test_sponsor_and_member_removes_have_confirm():
    assert "Remove this sponsor? Their logo and details are" in _SRC
    assert "Remove this member from the organisation?" in _SRC


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

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def test_layout_ships_confirm_helper(client):
    # Any signed-in page carries the shared MH.confirm helper in its chrome JS.
    html = client.get("/activity").get_data(as_text=True)
    assert "MH.confirm = function" in html
