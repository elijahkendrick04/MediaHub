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
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    yield tmp_path


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
def app_org(env):
    from mediahub.web.club_profile import ClubProfile, save_profile
    from mediahub.web.web import create_app

    save_profile(ClubProfile(profile_id=ORG, display_name="Quick SC"))
    app = create_app()
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
