"""Free-text chat robustness — residual hardening after PR #1103.

PR #1103's parallel free-text audit already landed tenant isolation, hashtag
normalisation, prompt-length caps and basic accept-idempotency. Two failure
modes it did not cover, fixed here and locked below:

1. A chat ``propose_brief`` uses an unconstrained tool schema, so the model can
   return a non-string ``headline``/``body`` (a list of lines, a nested object).
   ``_chat_brief_to_pack`` joined those verbatim, raising a ``TypeError`` that
   500'd Accept/Generate — and because the brief was already frozen as
   ``accepted_brief``, every retry hit the same crash (a permanently bricked
   chat). The build now coerces the fields to strings first.
2. ``save_session`` wrote the chat JSON in place, so a crash or an overlapping
   write mid-serialisation could truncate the file and lose the whole
   conversation. It now writes atomically (temp + ``os.replace``).
"""

from __future__ import annotations

import glob

import pytest

ORG = "robust-org"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    yield tmp_path


# ---------------------------------------------------------------------------
# save_session atomicity
# ---------------------------------------------------------------------------


def test_save_session_is_atomic_and_leaves_no_tmp(env):
    from mediahub.free_text_chat.session import (
        _sessions_dir,
        create_session,
        load_session,
        save_session,
    )

    s = create_session(profile_id=ORG)
    s.add_user_message("make a sponsor thank-you")
    save_session(s)

    # Round-trips, and the temp file used for the atomic swap is gone.
    assert load_session(s.chat_id).messages[0]["content"] == "make a sponsor thank-you"
    assert glob.glob(str(_sessions_dir() / "*.tmp")) == []


def test_save_session_overwrite_does_not_truncate(env):
    """A second save fully replaces the file (no partial/truncated JSON)."""
    from mediahub.free_text_chat.session import create_session, load_session, save_session

    s = create_session(profile_id=ORG)
    s.add_user_message("first")
    save_session(s)
    s.add_user_message("second")
    save_session(s)

    loaded = load_session(s.chat_id)
    assert [m["content"] for m in loaded.messages] == ["first", "second"]


# ---------------------------------------------------------------------------
# Non-string brief fields must not crash the chat -> pack build
# ---------------------------------------------------------------------------


@pytest.fixture
def app_org(env):
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id=ORG, display_name="Robust SC", brand_voice_summary="Bold."))
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app


def _pin(c):
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG


@pytest.mark.parametrize(
    "headline, body",
    [
        (["line one", "line two"], "a body"),  # list headline — used to 500
        ({"a": 1}, "a body"),  # dict headline
        ("a headline", ["b1", "b2"]),  # list body
        (42, 7),  # numbers
    ],
)
def test_generate_with_non_string_brief_fields_does_not_500(app_org, env, headline, body):
    from mediahub.club_platform.stub_pack_store import list_packs
    from mediahub.free_text_chat.session import create_session, save_session

    s = create_session(profile_id=ORG)
    s.accepted_brief = {
        "headline": headline,
        "body": body,
        "hashtags": "swimming pb",  # bare string — normalised, not char-split
        "platform": "Instagram",
        "visual_concept": ["bold", "type"],
    }
    save_session(s)

    with app_org.test_client() as c:
        _pin(c)
        r = c.post(f"/free-text/chat/{s.chat_id}/generate", follow_redirects=False)
        assert r.status_code == 302, r.status_code  # not a 500
        assert "/drafts/" in r.headers["Location"]

    packs = list_packs()
    assert len(packs) == 1  # a draft was actually built


def test_generate_non_string_hashtags_are_not_char_split(app_org, env):
    from mediahub.club_platform.stub_pack_store import list_packs, load_pack
    from mediahub.free_text_chat.session import create_session, save_session

    s = create_session(profile_id=ORG)
    s.accepted_brief = {
        "headline": "Great gala",
        "body": "Well done all",
        "hashtags": "swimming",  # bare string
        "platform": "Instagram",
    }
    save_session(s)

    with app_org.test_client() as c:
        _pin(c)
        r = c.post(f"/free-text/chat/{s.chat_id}/generate", follow_redirects=False)
        assert r.status_code == 302

    pack_id = list_packs()[0]["pack_id"]
    rec = load_pack(pack_id)
    tags = rec["cards"][0]["hashtags"]
    # One clean tag, not one-per-character.
    assert tags == ["swimming"]
