"""D-23 — raw internal exception text must never reach customers on the chat,
draft-graphic or public-demo surfaces.

Before this fix these three surfaces appended the raw Python exception verbatim
(``Error: <exc>``, ``render_failed: <exc>``, ``Parser said: <exc>``), which
reads like the product broke and leaks internals to (in the /try case)
anonymous first-time visitors at the top of the acquisition funnel. The fix
maps provider/render failures to plain-English copy and logs the raw exception
server-side only.
"""

from __future__ import annotations

import io
import json

import pytest

ORG = "d23-org"
# A distinctive marker that only ever appears inside a raw exception string, so
# the tests can assert it never surfaces to the customer.
LEAK = "SECRET-TRACEBACK-zx9q"


@pytest.fixture
def world(app, web_module, tmp_path):
    import mediahub.web.demo_try as dt

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="D23 SC"))
    return {"app": app, "wm": web_module, "dt": dt, "tmp": tmp_path}


# --- the shared helper --------------------------------------------------------


def test_friendly_message_never_echoes_raw_exception(world):
    wm = world["wm"]
    msg = wm._friendly_failure_message(RuntimeError(LEAK), kind="render")
    assert LEAK not in msg
    assert "try again" in msg.lower()


def test_friendly_message_provider_gap_is_honest(world):
    wm = world["wm"]

    class ProviderNotConfigured(RuntimeError):
        pass

    msg = wm._friendly_failure_message(ProviderNotConfigured("no key"), kind="ai")
    assert "administrator" in msg.lower()
    assert "provider" in msg.lower()


# --- draft graphic panel ------------------------------------------------------


def test_draft_graphic_render_failure_returns_friendly_user_message(world, monkeypatch):
    if not world["wm"]._v8_ok:
        pytest.skip("v8 rendering not available")
    from mediahub.club_platform.stub_pack_store import save_pack
    import mediahub.content_pack_visual.integration as integ

    rec = save_pack(
        "session_update",
        {"headline": "Great session"},
        [{"caption": "We had a brilliant swim session tonight."}],
        profile_id=ORG,
    )

    def _boom(*a, **k):
        raise RuntimeError(LEAK)

    monkeypatch.setattr(integ, "create_visual_for_item", _boom)

    c = world["app"].test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG
    r = c.post(
        f"/api/drafts/{rec['pack_id']}/card/0/create-graphic",
        data="{}",
        content_type="application/json",
    )
    assert r.status_code == 500
    body = r.get_json()
    # Machine code stays stable; the human copy is friendly and leak-free.
    assert body["error"] == "render_failed"
    assert LEAK not in json.dumps(body)
    assert "render_failed: " not in body.get("user_message", "")
    assert "try again" in body["user_message"].lower()


def test_visual_panel_js_prefers_user_message_over_raw_error(world):
    # The client render must surface user_message, not the raw error string,
    # and offer a Retry affordance rather than a dead error line.
    js = world["wm"]._VISUAL_PANEL_JS
    assert "user_message" in js
    assert "'Error: ' + esc(res.body.error" not in js
    assert "Try again" in js


# --- free-text chat -----------------------------------------------------------


def test_chat_turn_failure_shows_friendly_copy_not_raw_exception(world, monkeypatch):
    from mediahub.free_text_chat.session import create_session, save_session
    import mediahub.free_text_chat.agent as agent

    s = create_session()
    save_session(s)

    def _boom(*a, **k):
        raise RuntimeError(LEAK)

    monkeypatch.setattr(agent, "next_assistant_turn", _boom)

    c = world["app"].test_client()
    with c.session_transaction() as sess:
        sess["active_profile_id"] = ORG
    r = c.post(f"/free-text/chat/{s.chat_id}/send", data={"message": "hi there"})
    assert r.status_code in (302, 303)
    view = c.get(f"/free-text/chat/{s.chat_id}")
    html = view.get_data(as_text=True)
    assert LEAK not in html
    assert "Error: " + LEAK not in html
    # The friendly turn is honest about a transient failure or a provider gap.
    assert "try again" in html.lower() or "administrator" in html.lower()


# --- public /try demo ---------------------------------------------------------


def _seed_failed_demo_run(world, run_id, error_text):
    dt = world["dt"]
    runs_dir = world["tmp"] / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{run_id}.json").write_text(json.dumps({"profile_id": dt.DEMO_PROFILE_ID}))
    conn = world["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name, error) "
        "VALUES (?, datetime('now'), 'error', ?, ?, ?, ?)",
        (run_id, dt.DEMO_PROFILE_ID, "Demo Gala", "demo.hy3", error_text),
    )
    conn.commit()
    conn.close()


def test_try_failed_run_hides_raw_pipeline_error(world):
    _seed_failed_demo_run(world, "runfail00001", f"Traceback ... {LEAK}")
    c = world["app"].test_client()
    with c.session_transaction() as sess:
        sess["demo_runs"] = ["runfail00001"]
    r = c.get("/try/runfail00001")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert LEAK not in html
    assert "didn't finish" in html
    assert "Try another file" in html


def test_try_unparseable_file_hides_parser_exception(world):
    c = world["app"].test_client()
    r = c.post(
        "/try",
        data={"file": (io.BytesIO(b"not-a-real-meet-file-just-junk"), "meet.hy3")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Parser said" not in html
    assert "couldn't read that file" in html
