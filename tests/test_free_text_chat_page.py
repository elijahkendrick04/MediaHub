"""Regression coverage for the /free-text landing page's past-chats list.

A chat session's ``updated_at`` is always written as an ISO string by
``save_session`` (see ``free_text_chat/session.py``), but ``list_sessions``
reads it back with a bare ``dict.get`` and applies no type check — so a
hand-edited, migrated, or otherwise malformed session record whose
``updated_at`` isn't a string used to blow up ``free_text_chat_page`` with an
unhandled ``TypeError`` (``int``/``None`` aren't sliceable), 500ing the whole
Free-text landing page instead of just skipping the bad timestamp.
"""

from __future__ import annotations

import json

import pytest

ORG = "free-text-chat-org"


@pytest.fixture
def app_org(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id=ORG, display_name="Free Text SC"))
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app


def _pin(c):
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG


def test_free_text_page_renders_normal_session(app_org):
    from mediahub.free_text_chat.session import create_session

    s = create_session()
    s.add_user_message("thank our sponsor")
    from mediahub.free_text_chat.session import save_session

    save_session(s)

    with app_org.test_client() as c:
        _pin(c)
        r = c.get("/free-text")
        assert r.status_code == 200


def test_free_text_page_survives_non_string_updated_at(app_org, tmp_path):
    # Simulate a malformed/legacy chat session record on disk — bypasses
    # save_session entirely so updated_at can carry a type save_session
    # would never write.
    chats_dir = tmp_path / "free_text_chats"
    chats_dir.mkdir(parents=True, exist_ok=True)
    (chats_dir / "malformed1.json").write_text(
        json.dumps(
            {
                "chat_id": "malformed1",
                "created_at": 1234567890,
                "updated_at": 1234567890,
                "title": "Malformed timestamp chat",
                "messages": [],
                "pending_brief": None,
                "accepted_brief": None,
                "research_log": [],
            }
        )
    )
    with app_org.test_client() as c:
        _pin(c)
        r = c.get("/free-text")
        assert r.status_code == 200
        assert "Malformed timestamp chat" in r.get_data(as_text=True)
