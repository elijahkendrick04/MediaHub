"""Tenant isolation for Free Text chats (audit/free-text).

Regression coverage for the cross-tenant leak found in the Free Text audit:
web-created chats were never stamped with the creating organisation, the
landing list called ``list_sessions`` unscoped, and none of the chat
view/send/accept/decline/generate routes enforced ``can_access_session``.
The net effect was that org Beta could see org Alpha's chat titles (the first
line of a private brief — potential athlete PII), read Alpha's full transcript
and proposed/accepted brief, and drive/mutate Alpha's chat.

Mirrors the posture in ``tests/test_cross_tenant_access.py``: a foreign chat is
indistinguishable from a nonexistent one, and legacy ownerless chats stay
readable so history isn't orphaned.
"""

from __future__ import annotations

import pytest

ALPHA = "org-alpha"
BETA = "org-beta"
SECRET = "ALPHA PRIVATE — swimmer Jane Doe smashed the 100m club record"


@pytest.fixture
def app_two_orgs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id=ALPHA, display_name="Org Alpha"))
    save_profile(ClubProfile(profile_id=BETA, display_name="Org Beta"))
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app


def _pin(c, pid):
    with c.session_transaction() as s:
        s["active_profile_id"] = pid


def _alpha_chat_with_secret(c):
    """Alpha creates a chat via the web route and posts a private message."""
    _pin(c, ALPHA)
    r = c.post("/free-text/chat/new", follow_redirects=False)
    chat_id = r.headers["Location"].rstrip("/").split("/")[-1]
    # The user message is persisted before the (unconfigured) LLM turn.
    c.post(f"/free-text/chat/{chat_id}/send", data={"message": SECRET})
    return chat_id


def test_new_chat_is_stamped_with_active_org(app_two_orgs):
    from mediahub.free_text_chat.session import load_session

    with app_two_orgs.test_client() as c:
        chat_id = _alpha_chat_with_secret(c)
    assert load_session(chat_id).profile_id == ALPHA


def test_landing_list_does_not_leak_foreign_chat_titles(app_two_orgs):
    with app_two_orgs.test_client() as c:
        _alpha_chat_with_secret(c)
        _pin(c, BETA)
        body = c.get("/free-text").get_data(as_text=True)
    assert "Jane Doe" not in body
    assert "ALPHA PRIVATE" not in body


def test_foreign_org_cannot_read_transcript(app_two_orgs):
    with app_two_orgs.test_client() as c:
        chat_id = _alpha_chat_with_secret(c)
        _pin(c, BETA)
        r = c.get(f"/free-text/chat/{chat_id}")
        body = r.get_data(as_text=True)
    # A foreign chat reads as "not found" — no transcript leak.
    assert SECRET not in body
    assert "Jane Doe" not in body


def test_foreign_org_cannot_mutate_chat(app_two_orgs):
    from mediahub.free_text_chat.session import load_session

    with app_two_orgs.test_client() as c:
        chat_id = _alpha_chat_with_secret(c)
        _pin(c, BETA)
        c.post(
            f"/free-text/chat/{chat_id}/send",
            data={"message": "beta injected message"},
        )
    # Beta's message must never land in Alpha's transcript.
    msgs = [m.get("content", "") for m in load_session(chat_id).messages]
    assert "beta injected message" not in msgs


def test_foreign_org_cannot_accept_or_generate_from_brief(app_two_orgs):
    """Beta accepting/generating on Alpha's chat must not build a Beta pack
    out of Alpha's brief."""
    from mediahub.free_text_chat.session import load_session, save_session
    from mediahub.club_platform.stub_pack_store import list_packs

    with app_two_orgs.test_client() as c:
        chat_id = _alpha_chat_with_secret(c)
        # Hand-place a pending brief on Alpha's chat (skip the LLM).
        s = load_session(chat_id)
        s.pending_brief = {"headline": "ALPHA BRIEF", "body": "secret body"}
        save_session(s)

        _pin(c, BETA)
        c.post(f"/free-text/chat/{chat_id}/accept")
        c.post(f"/free-text/chat/{chat_id}/generate")

        # No pack was fabricated from Alpha's brief under any owner.
        assert list_packs() == []
        # Alpha's brief was not silently accepted by Beta's action.
        assert load_session(chat_id).accepted_brief is None


def test_owner_still_has_full_access(app_two_orgs):
    """Positive control — the guard must not lock the legitimate owner out."""
    from mediahub.free_text_chat.session import load_session, save_session

    with app_two_orgs.test_client() as c:
        chat_id = _alpha_chat_with_secret(c)
        _pin(c, ALPHA)
        # Landing lists her own chat.
        landing = c.get("/free-text").get_data(as_text=True)
        assert "Jane Doe" in landing
        # She can read her transcript.
        view = c.get(f"/free-text/chat/{chat_id}")
        assert view.status_code == 200
        assert "Jane Doe" in view.get_data(as_text=True)
        # She can accept + generate her own brief.
        s = load_session(chat_id)
        s.pending_brief = {"headline": "Own brief", "body": "own body"}
        save_session(s)
        r = c.post(f"/free-text/chat/{chat_id}/accept", follow_redirects=False)
        assert r.status_code == 302
    from mediahub.club_platform.stub_pack_store import list_packs

    assert len(list_packs()) == 1


def test_legacy_ownerless_chat_stays_readable(app_two_orgs):
    """Chats created before scoping (no profile_id) stay accessible to any
    org — mirrors the ownerless-run/pack lenience so history isn't orphaned."""
    from mediahub.free_text_chat.session import create_session, save_session

    s = create_session()  # no profile stamped
    s.add_user_message("legacy ownerless note")
    save_session(s)
    with app_two_orgs.test_client() as c:
        _pin(c, BETA)
        view = c.get(f"/free-text/chat/{s.chat_id}")
        assert view.status_code == 200
        assert "legacy ownerless note" in view.get_data(as_text=True)
