"""Single-prompt graphic builder — Free Text quick-build (bullet 13).

Covers the one-shot ``prompt -> brief`` interpreter and the
``/free-text/quick-build`` route that turns it into a saved draft which
auto-renders its graphic. The LLM is mocked (no network); the honest-error
rule is asserted explicitly (no fabricated brief without a provider).
"""

from __future__ import annotations

import pytest

ORG = "quick-org"

_GOOD_BRIEF = (
    '{"headline":"THANK YOU RIVERSIDE",'
    '"body":"A huge thank you to Riverside Physio for backing the club this season.",'
    '"hashtags":["sponsor","#thankyou"],"platform":"Instagram",'
    '"visual_concept":"bold thank-you in club colours","tone":"warm",'
    '"wants_reel":false,"title":"Sponsor thank-you"}'
)


@pytest.fixture
def env(tmp_path, web_module):
    """Private per-test DATA_DIR. Requesting ``web_module`` pulls in the canonical
    ``_isolate_data_dir`` fixture, which sets the storage-path env vars, repoints
    the already-imported ``web.py`` globals and clears its per-run caches — the
    same isolation the old ``setenv + importlib.reload`` boilerplate produced,
    without the reload. ``tmp_path`` is shared, so ``env`` is the DATA_DIR the app
    writes to."""
    return tmp_path


def _patch_ask(monkeypatch, *, returns=None, raises=None):
    import mediahub.ai_core as core

    def _fake_ask(system, user, **kw):
        if raises is not None:
            raise raises
        return returns

    monkeypatch.setattr(core, "ask", _fake_ask)
    # narrate_brand also routes through ask in some providers — keep it inert.
    monkeypatch.setattr(core, "narrate_brand", lambda *a, **k: "", raising=False)


# ---------------------------------------------------------------------------
# Chat session tenant scoping (workspace isolation)
# ---------------------------------------------------------------------------


def test_chat_sessions_are_profile_scoped(env):
    from mediahub.free_text_chat.session import (
        can_access_session,
        create_session,
        list_sessions,
        load_session,
    )

    a = create_session(profile_id="org-a")
    b = create_session(profile_id="org-b")

    # Owner sees only their own chat in the listing.
    ids_a = {r["chat_id"] for r in list_sessions(profile_id="org-a")}
    assert a.chat_id in ids_a and b.chat_id not in ids_a

    # Guard: the other org's chat is refused; own chat is allowed.
    assert can_access_session(load_session(a.chat_id), "org-a") is True
    assert can_access_session(load_session(a.chat_id), "org-b") is False
    assert can_access_session(None, "org-a") is False


def test_legacy_ownerless_chat_stays_accessible(env):
    """Chats persisted before scoping existed carry no profile_id — they
    must stay readable (mirrors _can_access_run's ownerless-run rule)."""
    from mediahub.free_text_chat.session import (
        can_access_session,
        create_session,
        list_sessions,
        load_session,
    )

    legacy = create_session()  # no profile stamped
    assert load_session(legacy.chat_id).profile_id == ""
    assert can_access_session(load_session(legacy.chat_id), "org-a") is True
    ids = {r["chat_id"] for r in list_sessions(profile_id="org-a")}
    assert legacy.chat_id in ids
    # No-orgs sandbox (active pid None) keeps everything reachable.
    assert can_access_session(load_session(legacy.chat_id), None) is True


def test_profile_id_survives_save_load_round_trip(env):
    from mediahub.free_text_chat.session import create_session, load_session, save_session

    s = create_session(profile_id="org-a")
    s.add_user_message("make a sponsor thank-you")
    save_session(s)
    loaded = load_session(s.chat_id)
    assert loaded.profile_id == "org-a"
    assert loaded.messages[0]["content"] == "make a sponsor thank-you"


# ---------------------------------------------------------------------------
# build_brief_from_prompt — one-shot interpreter
# ---------------------------------------------------------------------------


def test_build_brief_parses_json(env, monkeypatch):
    _patch_ask(monkeypatch, returns=_GOOD_BRIEF)
    from mediahub.free_text_chat.agent import build_brief_from_prompt

    brief = build_brief_from_prompt("thank our sponsor")
    assert brief["headline"] == "THANK YOU RIVERSIDE"
    assert brief["platform"] == "Instagram"
    # Leading '#' is stripped from hashtags.
    assert brief["hashtags"] == ["sponsor", "thankyou"]
    assert brief["wants_reel"] is False


def test_build_brief_tolerates_code_fences(env, monkeypatch):
    _patch_ask(monkeypatch, returns="```json\n" + _GOOD_BRIEF + "\n```")
    from mediahub.free_text_chat.agent import build_brief_from_prompt

    assert build_brief_from_prompt("x")["headline"] == "THANK YOU RIVERSIDE"


def test_build_brief_honest_error_on_garbage(env, monkeypatch):
    _patch_ask(monkeypatch, returns="sorry, I can't do that")
    from mediahub.free_text_chat.agent import build_brief_from_prompt
    from mediahub.ai_core import ProviderError

    with pytest.raises(ProviderError):
        build_brief_from_prompt("x")


def test_build_brief_propagates_no_provider(env, monkeypatch):
    from mediahub.ai_core import ProviderNotConfigured

    _patch_ask(monkeypatch, raises=ProviderNotConfigured("no key"))
    from mediahub.free_text_chat.agent import build_brief_from_prompt

    with pytest.raises(ProviderNotConfigured):
        build_brief_from_prompt("x")


def test_build_brief_empty_prompt_errors(env):
    from mediahub.free_text_chat.agent import build_brief_from_prompt
    from mediahub.ai_core import ProviderError

    with pytest.raises(ProviderError):
        build_brief_from_prompt("   ")


# ---------------------------------------------------------------------------
# /free-text/quick-build route
# ---------------------------------------------------------------------------


@pytest.fixture
def app_org(web_module):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Quick SC"))
    app = web_module.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app


def _pin(c):
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG


def test_quick_build_creates_pack_and_redirects_autographic(app_org, monkeypatch):
    _patch_ask(monkeypatch, returns=_GOOD_BRIEF)
    with app_org.test_client() as c:
        _pin(c)
        r = c.post(
            "/free-text/quick-build",
            data={"prompt": "thank our sponsor Riverside Physio"},
            follow_redirects=False,
        )
        assert r.status_code == 302
        loc = r.headers["Location"]
        assert "/drafts/" in loc and "autographic=1" in loc
        # The draft exists and carries the brief's caption + the auto-render hook.
        view = c.get(loc).get_data(as_text=True)
        assert "Riverside" in view
        assert "mhAutoGraphic" in view


def test_quick_build_no_prompt_redirects_back(app_org):
    with app_org.test_client() as c:
        _pin(c)
        r = c.post("/free-text/quick-build", data={"prompt": ""}, follow_redirects=False)
        assert r.status_code == 302
        assert "/free-text" in r.headers["Location"]


def test_quick_build_provider_error_is_honest(app_org, monkeypatch):
    from mediahub.ai_core import ProviderNotConfigured

    _patch_ask(monkeypatch, raises=ProviderNotConfigured("no provider configured"))
    with app_org.test_client() as c:
        _pin(c)
        r = c.post("/free-text/quick-build", data={"prompt": "hi"}, follow_redirects=False)
        assert r.status_code == 302 and "/free-text" in r.headers["Location"]
        # Honest error surfaced on the landing — and no draft was fabricated.
        body = c.get("/free-text").get_data(as_text=True)
        assert "provider" in body.lower() or "configured" in body.lower()
        from mediahub.club_platform.stub_pack_store import list_packs

        assert list_packs() == []


def test_draft_view_footer_replaces_default_anchor(app_org, monkeypatch, caplog):
    """The draft view swaps render_cards_html's default 'Start over' row for
    the export/regenerate footer — and the swap actually happened (no silent
    no-op, no drift warning)."""
    import logging

    _patch_ask(monkeypatch, returns=_GOOD_BRIEF)
    with app_org.test_client() as c:
        _pin(c)
        r = c.post(
            "/free-text/quick-build",
            data={"prompt": "thank our sponsor"},
            follow_redirects=False,
        )
        loc = r.headers["Location"]
        with caplog.at_level(logging.WARNING, logger="mediahub.web.web"):
            view = c.get(loc).get_data(as_text=True)
    # Footer injected, default lone anchor row replaced. (E-11 renamed the
    # blank-form link from "Generate new draft" to the unambiguous label.)
    assert "Start a new draft from the form" in view
    assert "All drafts" in view
    assert "← Start over" not in view
    assert "markup drifted" not in caplog.text


def test_draft_view_warns_loudly_on_marker_drift(app_org, monkeypatch, caplog):
    """If render_cards_html's anchor markup ever drifts, the replace must not
    fail silently (the PR-118 regression class): the page still renders and a
    warning names the miss."""
    import logging

    _patch_ask(monkeypatch, returns=_GOOD_BRIEF)
    with app_org.test_client() as c:
        _pin(c)
        r = c.post(
            "/free-text/quick-build",
            data={"prompt": "thank our sponsor"},
            follow_redirects=False,
        )
        loc = r.headers["Location"]
        # Simulate a future markup tweak: the emitted anchor no longer
        # matches what the view tries to replace.
        import mediahub.club_platform.stubs as stubs_mod

        real = stubs_mod.render_cards_html

        def drifted(*a, **k):
            return real(*a, **k).replace("← Start over", "⟵ Start over")

        monkeypatch.setattr(stubs_mod, "render_cards_html", drifted)
        with caplog.at_level(logging.WARNING, logger="mediahub.web.web"):
            resp = c.get(loc)
    assert resp.status_code == 200
    assert "markup drifted" in caplog.text


def test_quick_build_photos_share_the_ingest_gate(env, web_module, monkeypatch):
    """Quick-build photos go through the shared ingest gate (sub_25r-1): a
    HEIC upload is normalised to JPEG (decoder present) or skipped (absent) —
    never stored raw as an undecodable graphic background — and corrupt
    bytes are skipped, not saved."""
    import io as _io

    if not web_module._v8_ok:
        pytest.skip("v8 engine unavailable")
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Quick SC"))
    app = web_module.create_app()
    app.config.update(TESTING=True, SECRET_KEY="x")
    _patch_ask(monkeypatch, returns=_GOOD_BRIEF)

    from PIL import Image

    jpg = _io.BytesIO()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(jpg, format="JPEG")
    jpg.seek(0)

    heic_buf = None
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        heic_buf = _io.BytesIO()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(heic_buf, format="HEIF")
        heic_buf.seek(0)
    except Exception:
        heic_buf = None  # no encoder here — the corrupt case still covers the gate

    files = [(jpg, "good.jpg"), (_io.BytesIO(b"not-a-heic"), "corrupt.heic")]
    if heic_buf is not None:
        files.append((heic_buf, "real.heic"))

    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = ORG
        r = c.post(
            "/free-text/quick-build",
            data={"prompt": "thank our sponsor", "photos": files},
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert r.status_code == 302, r.status_code

    lib_dir = env / "uploads_v4" / "media_library" / ORG
    stored = [p.name for p in lib_dir.glob("*")] if lib_dir.exists() else []
    # No raw .heic/.heif may ever remain on disk.
    assert not [n for n in stored if n.lower().endswith((".heic", ".heif"))], stored
    # The plain JPEG (plus the normalised HEIC when the decoder exists) landed.
    expected = 1 + (1 if heic_buf is not None else 0)
    jpgs = [n for n in stored if n.lower().endswith((".jpg", ".jpeg"))]
    assert len(jpgs) == expected, stored
