"""Regression coverage for the Free Text hardening fixes (audit/free-text).

Companion to test_free_text_chat_tenant_isolation.py. Locks the smaller
correctness / UX / robustness fixes surfaced by the audit:

  FT-DATA-1  accept is idempotent — a double-submit doesn't mint two drafts
  FT-VAL-1   over-long prompts / replies are rejected before the LLM call
  FT-DATA-2  chat-brief hashtags are coerced to a clean list (no per-char chips)
  FT-ERR-2   the chat view shows the AI-unavailable banner up front
  FT-A11Y-1  the "Add photos" control is keyboard-operable
  FT-COPY-1  the reply strap is provider-neutral (agent is provider-agnostic)
"""

from __future__ import annotations

import pytest

ORG = "riverside"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(
        ClubProfile(profile_id=ORG, display_name="Riverside SC", brand_voice_summary="Warm.")
    )
    app = create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app


@pytest.fixture
def client(app):
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = ORG
        yield c


def _chat_with_pending_brief(client, brief):
    """Create a chat owned by ORG and hand-place a pending brief (skip LLM)."""
    from mediahub.free_text_chat.session import load_session, save_session

    r = client.post("/free-text/chat/new", follow_redirects=False)
    chat_id = r.headers["Location"].rstrip("/").split("/")[-1]
    s = load_session(chat_id)
    s.add_user_message("Celebrate the relay team")
    s.pending_brief = brief
    save_session(s)
    return chat_id


# --- FT-DATA-1: accept idempotency -----------------------------------------

def test_accept_is_idempotent(app, client):
    from mediahub.club_platform.stub_pack_store import list_packs

    chat_id = _chat_with_pending_brief(client, {"headline": "Relay glory", "body": "x"})
    # First accept builds exactly one draft and lands on it.
    r1 = client.post(f"/free-text/chat/{chat_id}/accept", follow_redirects=False)
    assert r1.status_code == 302
    assert len(list_packs()) == 1
    # Second (stale/double) accept must NOT mint a second draft.
    r2 = client.post(f"/free-text/chat/{chat_id}/accept", follow_redirects=False)
    assert r2.status_code == 302
    assert len(list_packs()) == 1


def test_generate_remains_the_explicit_regenerate_path(app, client):
    """/generate is the deliberate 'make a draft from this brief' action and may
    be used after accept — it is not blocked by the accept-idempotency change."""
    from mediahub.club_platform.stub_pack_store import list_packs

    chat_id = _chat_with_pending_brief(client, {"headline": "Relay glory", "body": "x"})
    client.post(f"/free-text/chat/{chat_id}/accept")
    assert len(list_packs()) == 1
    client.post(f"/free-text/chat/{chat_id}/generate")
    assert len(list_packs()) == 2


# --- FT-VAL-1: input length cap --------------------------------------------

def test_quick_build_rejects_overlong_prompt(app, client):
    from mediahub.club_platform.stub_pack_store import list_packs

    huge = "x" * 9000
    r = client.post("/free-text/quick-build", data={"prompt": huge}, follow_redirects=False)
    assert r.status_code == 302  # bounced, not processed
    assert list_packs() == []  # no draft built
    with client.session_transaction() as s:
        assert "character" in (s.get("free_text_quick_error") or "").lower()


def test_chat_send_rejects_overlong_message(app, client):
    from mediahub.free_text_chat.session import load_session

    r = client.post("/free-text/chat/new", follow_redirects=False)
    chat_id = r.headers["Location"].rstrip("/").split("/")[-1]
    huge = "y" * 9000
    client.post(f"/free-text/chat/{chat_id}/send", data={"message": huge})
    s = load_session(chat_id)
    # The giant message is not stored as a user turn...
    assert all(huge not in m.get("content", "") for m in s.messages)
    # ...and the user is told to shorten it.
    assert any("shorten" in m.get("content", "").lower() for m in s.messages)


def test_normal_length_prompt_is_not_blocked(app, client):
    """A realistic prompt still reaches the (unconfigured) LLM path and only
    fails with the honest AI-unavailable error, not a length rejection."""
    r = client.post(
        "/free-text/quick-build",
        data={"prompt": "Thank our sponsor Riverside Physio after a great gala."},
        follow_redirects=False,
    )
    assert r.status_code == 302
    with client.session_transaction() as s:
        err = (s.get("free_text_quick_error") or "").lower()
    assert "character" not in err  # not a length rejection


# --- FT-DATA-2: hashtag coercion -------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        (["#Swim", " Relay ", "#PB"], ["Swim", "Relay", "PB"]),
        ("#Swim #Relay #PB", ["Swim", "Relay", "PB"]),  # string, not a list
        ("#Swim,#Relay", ["Swim", "Relay"]),
        ({"unexpected": "dict"}, []),  # unexpected shape drops to empty, not chips
        (None, []),
    ],
)
def test_chat_brief_hashtags_coerced_to_clean_list(app, client, raw, expected):
    from mediahub.free_text_chat.session import load_session, save_session
    from mediahub.club_platform.stub_pack_store import list_packs, load_pack

    chat_id = _chat_with_pending_brief(
        client, {"headline": "H", "body": "B", "hashtags": raw}
    )
    client.post(f"/free-text/chat/{chat_id}/accept")
    pack = load_pack(list_packs()[0]["pack_id"])
    tags = pack["cards"][0]["hashtags"]
    assert isinstance(tags, list)
    assert tags == expected


# --- FT-ERR-2 / FT-COPY-1: chat view banner + provider-neutral copy --------

def test_chat_view_shows_ai_unavailable_banner_and_neutral_copy(app, client):
    r = client.post("/free-text/chat/new", follow_redirects=False)
    chat_id = r.headers["Location"].rstrip("/").split("/")[-1]
    body = client.get(f"/free-text/chat/{chat_id}").get_data(as_text=True)
    # FT-ERR-2: the AI-off state is surfaced up front (no provider configured).
    assert "AI features unavailable" in body
    # FT-COPY-1: the strap no longer hard-codes a single provider.
    assert "Assistant uses Claude" not in body
    assert "AI assistant" in body


# --- FT-A11Y-1: photo control keyboard-operable ----------------------------

def test_add_photos_control_is_keyboard_operable(app, client):
    body = client.get("/free-text").get_data(as_text=True)
    # The label is focusable and exposes a button role + a keydown activator,
    # so keyboard-only users can open the file picker.
    assert 'tabindex="0"' in body
    assert 'role="button"' in body
    assert "onkeydown=" in body


# --- FT-VAL-2: hashtag normaliser is shared + string-safe ------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("swimwin", ["swimwin"]),  # bare string is NOT char-exploded
        ("#a #b #c", ["a", "b", "c"]),
        ("#a,#b", ["a", "b"]),
        (["#a", " b ", "", "#c"], ["a", "b", "c"]),
        (None, []),
        (12, []),  # unexpected scalar drops to empty
        (["#" + str(i) for i in range(20)], ["#" + str(i) for i in range(20)][:8]),
    ],
)
def test_normalise_hashtags(raw, expected):
    from mediahub.free_text_chat.agent import normalise_hashtags

    out = normalise_hashtags(raw)
    if raw == ["#" + str(i) for i in range(20)]:
        # last case: verify the ≤8 cap, tags de-#'d
        assert out == [str(i) for i in range(8)]
    else:
        assert out == expected


def test_quick_brief_parser_does_not_char_explode_string_hashtags():
    from mediahub.free_text_chat.agent import _parse_brief_json

    brief = _parse_brief_json('{"headline":"Big win","body":"","hashtags":"swimwin"}')
    assert brief["hashtags"] == ["swimwin"]


# --- FT-ERR-1: an errored turn must not leave an approvable brief ----------

def test_errored_turn_rolls_back_proposed_brief(app, monkeypatch):
    """If the model proposes a brief and a later round then errors, the
    half-finished brief must be rolled back — not left as an approvable card."""
    import mediahub.ai_core as ai_core
    from mediahub.ai_core import ProviderError
    from mediahub.free_text_chat.session import create_session
    from mediahub.free_text_chat.agent import next_assistant_turn

    def fake_ask_with_tools(*, system, user, tools, on_tool_call, **kw):
        # Model proposes a brief (sets pending_brief) then the turn errors.
        on_tool_call("propose_brief", {"brief": {"headline": "H", "body": "B"}, "summary": "s"})
        raise ProviderError("transient upstream 502")

    monkeypatch.setattr(ai_core, "ask_with_tools", fake_ask_with_tools)

    s = create_session(profile_id=ORG)
    s.add_user_message("make me a post")
    out = next_assistant_turn(s)
    assert out["kind"] == "error"
    # The brief from the failed turn must not survive.
    assert s.pending_brief is None
