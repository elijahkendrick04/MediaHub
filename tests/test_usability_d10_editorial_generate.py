"""D-10 — Documents/Newsletters generate must use a per-button "Write with AI"
toggle, a busy state, and styled errors — not an ambiguous confirm() and raw
alert().

The whole Documents+Newsletters area drove a *product* decision through a native
confirm ("OK = AI draft · Cancel = build from data only" — which gives no hint
which is which, and Cancel still generated), showed no busy state (a double-click
made duplicates), and reported failures via raw alert() with codes like
"generate_failed". Generate buttons now carry a "Write with AI" checkbox, disable
and show "Generating…" during the request, and report failures via MH.toast with
plain-English text.
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


@pytest.fixture
def client(tmp_path, monkeypatch):
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
    return c


def test_ambiguous_confirm_chooser_gone():
    assert "OK = AI draft" not in _SRC
    assert "Cancel = build from data only" not in _SRC


def test_documents_home_has_ai_toggle_and_busy_state(client):
    html = client.get("/documents").get_data(as_text=True)
    assert 'class="mh-ai-toggle"' in html
    assert "Write the wording with AI" in html
    # Buttons pass themselves so the handler can disable them + read the toggle.
    assert "genDoc(this," in html
    assert "function _genBusy(btn, on)" in html
    assert "'Generating…'" in html


def test_newsletters_home_has_ai_toggle(client):
    html = client.get("/newsletters").get_data(as_text=True)
    assert 'class="mh-ai-toggle"' in html
    assert "genNl(this," in html


def test_failures_are_toasts_not_raw_alerts(client):
    html = client.get("/documents").get_data(as_text=True)
    # The generate error path routes through MH.toast with mapped plain text.
    assert "function _genToast(m, kind)" in html
    assert "function _genMsg(j)" in html
    assert "Could not generate — please try again." in html
