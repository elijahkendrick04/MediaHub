"""E-11 — Regenerate (fresh angles) confirms first, and replaced captions are
visible in a "Previous versions" expander.

mhRegenerateDraft used to POST with no confirmation, silently replacing every
card; replace_cards archived the prior captions into card_history, which no
page displayed; and the adjacent "Generate new draft" link (which just opens
the blank source form) read like a second regenerate. Now: the handler runs
through MH.confirm, the draft page renders card_history (most recent first),
and the blank-form link is labelled "Start a new draft from the form".
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
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


def _save_pack():
    from mediahub.club_platform.stub_pack_store import save_pack

    return save_pack(
        "free_text",
        {"free_text": "Sam swam a huge PB"},
        [
            {"platform": "Instagram", "caption": "Huge PB for Sam!", "confidence": None},
            {"platform": "Stories", "caption": "What a swim.", "confidence": None},
        ],
        profile_id="club-a",
    )


def test_regenerate_handler_confirms_first(client):
    pack = _save_pack()
    pid = pack["pack_id"]
    view = client.get(f"/drafts/{pid}").get_data(as_text=True)
    # The handler routes through the styled confirm before any POST.
    assert "MH.confirm" in view
    assert "Regenerate this draft?" in view
    assert "clears their approval status" in view
    assert "Previous versions" in view  # the confirm copy names the expander
    # The button passes the live card count into the confirm copy.
    assert f"mhRegenerateDraft(this, '/api/drafts/{pid}/regenerate', 2)" in view


def test_previous_versions_expander_renders_history(client):
    from mediahub.club_platform.stub_pack_store import replace_cards

    pack = _save_pack()
    pid = pack["pack_id"]

    # No history yet — no expander.
    view = client.get(f"/drafts/{pid}").get_data(as_text=True)
    assert "Previous versions (" not in view

    replace_cards(
        pid,
        [{"platform": "Instagram", "caption": "Fresh angle one", "confidence": None}],
    )
    view = client.get(f"/drafts/{pid}").get_data(as_text=True)
    assert "Previous versions (2)" in view
    assert "Huge PB for Sam!" in view
    assert "What a swim." in view
    # Most recent first: the later-archived caption appears before the earlier.
    assert view.index("What a swim.") < view.index("Huge PB for Sam!")


def test_blank_form_link_renamed(client):
    pack = _save_pack()
    view = client.get(f"/drafts/{pack['pack_id']}").get_data(as_text=True)
    assert "Start a new draft from the form" in view
    assert "Generate new draft" not in view
