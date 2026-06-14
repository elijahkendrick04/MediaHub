"""tests/test_notifications_routes.py — the notifications inbox web surface (UI 1.14).

Pins the bell-icon API + chrome: org-scoped GET with unread count, mark-read /
mark-all-read, signed-out safety (an empty payload, never a 403 the poll has to
special-case), multi-tenant isolation, server-built deep links, the ?unread /
?limit query params, and the bell rendering only when signed in.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app_ctx(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.notify.inbox as ib
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(ib)
    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(profile_id="org-a", display_name="Org A", brand_voice_summary="Bold.")
    )
    save_profile(
        ClubProfile(profile_id="org-b", display_name="Org B", brand_voice_summary="Calm.")
    )

    app = wm.create_app()
    app.config["TESTING"] = True
    return {"wm": wm, "ib": ib, "client": app.test_client()}


def _pin(client, pid):
    r = client.post("/api/organisation/active", data={"profile_id": pid})
    assert r.status_code == 200, r.get_json()


def test_signed_out_returns_empty_payload(app_ctx):
    r = app_ctx["client"].get("/api/notifications")
    assert r.status_code == 200
    assert r.get_json() == {"ok": True, "unread": 0, "items": []}


def test_list_and_unread_scoped_to_org(app_ctx):
    ib, c = app_ctx["ib"], app_ctx["client"]
    ib.record_pack_ready("org-a", "run-a", count=2)
    ib.record_error("org-b", "B error", "x", run_id="run-b")
    _pin(c, "org-a")
    j = c.get("/api/notifications").get_json()
    assert j["unread"] == 1
    assert len(j["items"]) == 1
    assert j["items"][0]["kind"] == "pack_ready"
    # org-a must never see org-b's events
    assert all(it["title"] != "B error" for it in j["items"])


def test_deep_link_built_from_run(app_ctx):
    ib, c = app_ctx["ib"], app_ctx["client"]
    ib.record_pack_ready("org-a", "run-xyz", count=1)
    ib.record_render_complete("org-a", run_id="run-xyz", label="reel")
    _pin(c, "org-a")
    items = c.get("/api/notifications").get_json()["items"]
    by_kind = {it["kind"]: it for it in items}
    # pack-ready / error point at the review page; a finished render at the pack.
    assert by_kind["pack_ready"]["link"] == "/review/run-xyz"
    assert by_kind["render_complete"]["link"] == "/pack/run-xyz"


def test_explicit_click_url_wins_over_run_link(app_ctx):
    ib, c = app_ctx["ib"], app_ctx["client"]
    ib.record("org-a", "info", "t", run_id="run-xyz", click_url="/somewhere")
    _pin(c, "org-a")
    assert c.get("/api/notifications").get_json()["items"][0]["link"] == "/somewhere"


def test_no_run_means_no_link(app_ctx):
    ib, c = app_ctx["ib"], app_ctx["client"]
    ib.record("org-a", "info", "t")
    _pin(c, "org-a")
    assert c.get("/api/notifications").get_json()["items"][0]["link"] == ""


def test_mark_read_and_read_all(app_ctx):
    ib, c = app_ctx["ib"], app_ctx["client"]
    a = ib.record("org-a", "info", "a")
    ib.record("org-a", "info", "b")
    _pin(c, "org-a")
    assert c.get("/api/notifications").get_json()["unread"] == 2
    r = c.post(f"/api/notifications/{a}/read").get_json()
    assert r["changed"] is True and r["unread"] == 1
    r = c.post("/api/notifications/read-all").get_json()
    assert r["unread"] == 0
    assert c.get("/api/notifications").get_json()["unread"] == 0


def test_cannot_mark_other_orgs_notification(app_ctx):
    ib, c = app_ctx["ib"], app_ctx["client"]
    a = ib.record("org-a", "info", "secret-a")
    _pin(c, "org-b")
    r = c.post(f"/api/notifications/{a}/read").get_json()
    assert r["changed"] is False
    # org-a's notification is untouched
    assert ib.unread_count("org-a") == 1


def test_read_routes_require_active_org(app_ctx):
    c = app_ctx["client"]
    assert c.post("/api/notifications/x/read").status_code == 403
    assert c.post("/api/notifications/read-all").status_code == 403


def test_unread_and_limit_query_params(app_ctx):
    ib, c = app_ctx["ib"], app_ctx["client"]
    a = ib.record("org-a", "info", "a")
    for i in range(5):
        ib.record("org-a", "info", f"n{i}")
    ib.mark_read("org-a", a)
    _pin(c, "org-a")
    unread = c.get("/api/notifications?unread=1").get_json()["items"]
    assert unread and all(it["read"] is False for it in unread)
    limited = c.get("/api/notifications?limit=2").get_json()["items"]
    assert len(limited) == 2


def test_bell_renders_only_when_signed_in(app_ctx):
    # The bell *element* carries id="mh-notif-btn"; the CSS rule `.mh-notif-btn`
    # ships on every page, so assert on the element marker, not the bare class.
    c = app_ctx["client"]
    assert 'id="mh-notif-btn"' not in c.get("/", follow_redirects=True).get_data(as_text=True)
    _pin(c, "org-a")
    html = c.get("/", follow_redirects=True).get_data(as_text=True)
    assert 'id="mh-notif-btn"' in html
    assert 'data-list-url="/api/notifications"' in html
