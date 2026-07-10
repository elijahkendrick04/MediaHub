"""J-12 & H-8 — the offline shell must not dead-end, and an AI failure on the
free-text quick build must not throw away the volunteer's prompt.

J-12: the service worker's offline navigate fallback showed only "You are
offline" with no retry, no auto-refresh, no way back. It now has a Try-again
button, auto-reloads on the `online` event, and links back into the app.

H-8: when the LLM errors/isn't configured, quick-build stashed only the error and
redirected to a page whose textarea rendered empty — the typed prompt was lost.
It now stashes the prompt too and pre-fills the textarea.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)

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


def test_offline_shell_has_retry_reload_and_link(env):
    sw = env.get("/sw.js").get_data(as_text=True)
    assert "You are offline" in sw
    # Manual retry, auto-reload on reconnect, and a way back into the app.
    assert "location.reload()" in sw
    assert 'addEventListener("online"' in sw
    assert ">Try again</button>" in sw
    assert ">Back to MediaHub</a>" in sw


def test_offline_shell_was_a_dead_end_before(env):
    # The old fallback ended right after the "will sync" paragraph with no controls.
    sw = env.get("/sw.js").get_data(as_text=True)
    assert "will sync when you reconnect.</p></div></body>" not in sw


def test_quick_build_failure_preserves_prompt(env):
    # No LLM key in the test env -> build_brief_from_prompt raises -> honest error.
    prompt = "A bold thank-you post for our sponsor Riverside Physio after a great gala weekend."
    r = env.post(
        "/free-text/quick-build",
        data={"prompt": prompt},
        content_type="multipart/form-data",
    )
    assert r.status_code in (302, 303)
    # The follow-up page pre-fills the textarea with the typed prompt (not empty).
    page = env.get("/free-text").get_data(as_text=True)
    assert prompt in page
    # …and shows the honest error, not a fabricated graphic.
    assert 'class="mh-flash error"' in page


def test_quick_build_prompt_is_one_shot(env):
    """The stashed prompt is popped — a fresh visit isn't pre-filled."""
    env.post("/free-text/quick-build", data={"prompt": "one shot"}, content_type="multipart/form-data")
    env.get("/free-text")  # consumes the stash
    page2 = env.get("/free-text").get_data(as_text=True)
    assert "one shot" not in page2
