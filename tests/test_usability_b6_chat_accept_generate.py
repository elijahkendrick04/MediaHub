"""B-6 — the chat flow's "Accept & generate" must actually generate.

After refining a brief in chat, "Accept & generate" only marked the brief
accepted and reloaded; the user then had to find a second "Generate content from
this brief" button and land on a blank draft needing a third "Create graphic"
click. The button now accepts *and* builds the draft in one POST and redirects to
the pack with ?autographic=1, so the chat path ends on a rendering graphic like
the quick path.
"""

from __future__ import annotations

import importlib
import pathlib

import pytest

_SRC = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")


def test_generate_and_accept_both_use_autographic():
    # A shared helper builds the pack and both entry points land on the graphic.
    assert "_chat_brief_to_pack" in _SRC
    assert 'url_for("stub_pack_view", pack_id=saved["pack_id"]) + "?autographic=1"' in _SRC


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


_BRIEF = {
    "platform": "Instagram",
    "headline": "County champs recap",
    "body": "A brilliant weekend in the pool.",
    "hashtags": ["#swim"],
    "visual_concept": "hero shot of the relay team",
}


def _chat_with(pending=None, accepted=None):
    from mediahub.free_text_chat.session import create_session, save_session

    s = create_session(profile_id="club-a")
    s.title = "County champs"
    s.pending_brief = pending
    s.accepted_brief = accepted
    save_session(s)
    return s.chat_id


def test_accept_generates_and_lands_on_graphic(client):
    chat_id = _chat_with(pending=dict(_BRIEF))
    r = client.post(f"/free-text/chat/{chat_id}/accept")
    assert r.status_code == 302
    loc = r.headers["Location"]
    # Not a bounce back to the chat view — a real draft with the graphic rendering.
    assert "/drafts/" in loc or "/drafts" in loc
    assert "autographic=1" in loc

    from mediahub.free_text_chat.session import load_session

    s = load_session(chat_id)
    assert s.accepted_brief is not None  # brief was accepted as part of the same POST
    assert s.pending_brief is None


def test_generate_step_also_lands_on_graphic(client):
    chat_id = _chat_with(accepted=dict(_BRIEF))
    r = client.post(f"/free-text/chat/{chat_id}/generate")
    assert r.status_code == 302
    assert "autographic=1" in r.headers["Location"]


def test_accept_without_brief_falls_back_to_chat(client):
    chat_id = _chat_with()  # nothing pending or accepted
    r = client.post(f"/free-text/chat/{chat_id}/accept")
    assert r.status_code == 302
    # No brief to build → returns to the chat view, not a broken pack link.
    assert "autographic=1" not in r.headers["Location"]
