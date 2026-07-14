"""Email & newsletter composer (roadmap 1.17) — build 3: the web surface."""

from __future__ import annotations

import json
from datetime import date

import pytest


@pytest.fixture
def app_env(web_module, tmp_path, monkeypatch):
    # DATA_DIR isolation + one-time web.py import come from the autouse
    # ``_isolate_data_dir`` fixture in conftest.py.
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")
    for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "MEDIAHUB_LLM_PROVIDER"):
        monkeypatch.delenv(var, raising=False)
    app = web_module.create_app()
    app.config["TESTING"] = True
    return app, web_module, tmp_path


def _login(client, pid="club-a"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=pid, display_name=pid.replace("-", " ").title()))
    with client.session_transaction() as s:
        s["active_profile_id"] = pid


def _seed_approved_run(tmp_path, run_id="r1", profile_id="club-a"):
    rd = tmp_path / "runs_v4"
    rd.mkdir(parents=True, exist_ok=True)
    run = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "County Champs", "date": date.today().isoformat()},
        "recognition_report": {
            "ranked_achievements": [
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Ada Lovelace",
                                 "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1"}, "priority": 0.9, "rank": 1},
                {"achievement": {"type": "medal_gold", "swimmer_name": "Bo Pei",
                                 "swimmer_id": "s2", "event": "50m Back", "swim_id": "a2"}, "priority": 0.8, "rank": 2},
            ]
        },
        "cards": [],
    }
    (rd / f"{run_id}.json").write_text(json.dumps(run))
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    ws = WorkflowStore(rd)
    ws.set_status(run_id, "a1", CardStatus.APPROVED)
    ws.set_status(run_id, "a2", CardStatus.APPROVED)


def _generate(client, fmt="monthly_roundup", rng="this_season", with_ai=False):
    return client.post(
        "/api/newsletters/generate",
        json={"format": fmt, "range": rng, "with_ai": with_ai},
    )


def test_home_renders_with_format_tiles(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    r = c.get("/newsletters")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Newsletters" in html
    assert "Monthly roundup" in html and "Meet digest" in html and "Season highlights" in html


def test_home_requires_org(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    r = c.get("/newsletters")
    assert r.status_code == 200
    assert "Pick an organisation first" in r.get_data(as_text=True)


def test_generate_without_ai_then_view(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    _seed_approved_run(tmp)
    r = _generate(c)
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True and j["newsletter_id"].startswith("nl_")
    # the editor renders
    v = c.get(j["url"])
    assert v.status_code == 200
    assert "Download email HTML" in v.get_data(as_text=True)


def test_generate_with_ai_no_provider_is_honest(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    _seed_approved_run(tmp)
    r = _generate(c, with_ai=True)
    assert r.status_code == 200
    assert r.get_json()["error"] == "no_ai"


def test_html_export_is_email_safe_and_downloadable(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    _seed_approved_run(tmp)
    nid = _generate(c).get_json()["newsletter_id"]
    # inline
    r = c.get(f"/api/newsletters/{nid}/html")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert body.startswith("<!DOCTYPE html>")
    assert 'role="presentation"' in body  # table-based email HTML
    assert "100m Free" in body  # approved content (the swim) reached the email
    # download
    rd = c.get(f"/api/newsletters/{nid}/html?dl=1")
    assert "attachment" in rd.headers.get("Content-Disposition", "")


def test_text_export(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    _seed_approved_run(tmp)
    nid = _generate(c).get_json()["newsletter_id"]
    r = c.get(f"/api/newsletters/{nid}/text")
    assert r.status_code == 200
    assert "<" not in r.get_data(as_text=True)


def test_save_and_delete(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    nid = _generate(c).get_json()["newsletter_id"]
    # edit the title via the advanced spec save
    from mediahub.email_design import store as ns

    spec = ns.load_newsletter("club-a", nid)
    data = spec.to_dict()
    data["title"] = "Edited Title"
    r = c.post(f"/api/newsletters/{nid}/save", json={"spec": data})
    assert r.get_json()["ok"] is True
    assert ns.load_newsletter("club-a", nid).title == "Edited Title"
    # delete
    d = c.post(f"/api/newsletters/{nid}/delete")
    assert d.get_json()["ok"] is True
    assert ns.load_newsletter("club-a", nid) is None


def test_publish_serves_hosted_view_and_unpublish_revokes(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    _seed_approved_run(tmp)
    nid = _generate(c).get_json()["newsletter_id"]
    pub = c.post(f"/api/newsletters/{nid}/publish")
    assert pub.get_json()["ok"] is True
    from mediahub.email_design import store as ns

    rec = ns.newsletter_record("club-a", nid)
    token = rec["public_token"]
    # hosted view works (unauthenticated client)
    anon = app.test_client()
    hv = anon.get(f"/newsletter/{token}")
    assert hv.status_code == 200
    assert hv.get_data(as_text=True).startswith("<!DOCTYPE html>")
    # unpublish revokes
    c.post(f"/api/newsletters/{nid}/unpublish")
    assert anon.get(f"/newsletter/{token}").status_code == 404


def test_tenant_isolation_on_view_and_export(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c, "club-a")
    nid = _generate(c).get_json()["newsletter_id"]
    # a different org cannot see or export it
    other = app.test_client()
    _login(other, "club-b")
    miss = other.get(f"/newsletters/{nid}")
    assert miss.status_code == 404  # not-found recovery page
    assert "Newsletter not found" in miss.get_data(as_text=True)
    assert other.get(f"/api/newsletters/{nid}/html").status_code == 404


def test_public_card_route_rejects_unknown_token(app_env):
    app, wm, tmp = app_env
    anon = app.test_client()
    assert anon.get("/newsletter/not-a-token").status_code == 404
    assert anon.get("/newsletter/not-a-token/card/r1/a1.png").status_code == 404


def _seed_visual(tmp_path, run_id, card_id, brief):
    vdir = tmp_path / "runs_v4" / run_id / "visuals" / brief
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "visual.json").write_text(json.dumps({"content_item_id": card_id, "id": brief}))
    (vdir / "feed_portrait.png").write_bytes(b"\x89PNG fake")


def _save_card_ref_spec(client, nid, card_refs):
    from mediahub.email_design import store as ns

    data = ns.load_newsletter("club-a", nid).to_dict()
    data["sections"] = [
        {
            "blocks": [
                {"kind": "card", "props": {"title": "T", "body": "b", "card_ref": ref}}
                for ref in card_refs
            ]
        }
    ]
    r = client.post(f"/api/newsletters/{nid}/save", json={"spec": data})
    assert r.get_json()["ok"] is True


def test_published_card_images_are_snapshot_scoped(app_env):
    """The public token only unlocks cards the published snapshot references —
    never every wall-eligible card of the org."""
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    _seed_approved_run(tmp)  # a1 + a2 both approved
    _seed_visual(tmp, "r1", "a1", "brief-a")
    _seed_visual(tmp, "r1", "a2", "brief-b")
    nid = _generate(c, fmt="blank").get_json()["newsletter_id"]
    _save_card_ref_spec(c, nid, ["r1/a1"])
    c.post(f"/api/newsletters/{nid}/publish")
    from mediahub.email_design import store as ns

    token = ns.newsletter_record("club-a", nid)["public_token"]
    anon = app.test_client()
    # the referenced approved card resolves…
    assert anon.get(f"/newsletter/{token}/card/r1/a1.png").status_code == 200
    # …but the token does NOT unlock other approved cards of the org
    assert anon.get(f"/newsletter/{token}/card/r1/a2.png").status_code == 404
    # the authenticated editor preview route is draft-scoped the same way
    assert c.get(f"/newsletters/{nid}/card/r1/a1.png").status_code == 200
    assert c.get(f"/newsletters/{nid}/card/r1/a2.png").status_code == 404


def test_newsletter_images_ignore_wall_exclusion_but_keep_approval_gate(app_env):
    """A wall-excluded approved card still renders in a newsletter (the wall is a
    different surface); an unapproved card stays blocked, with an explained
    placeholder in the editor preview."""
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    _seed_approved_run(tmp)  # a1 approved; a3 never approved
    _seed_visual(tmp, "r1", "a1", "brief-a")
    _seed_visual(tmp, "r1", "a3", "brief-c")
    from mediahub.web.club_profile import load_profile, save_profile

    prof = load_profile("club-a")
    prof.public_wall_excluded_cards = ["r1::a1"]
    save_profile(prof)
    nid = _generate(c, fmt="blank").get_json()["newsletter_id"]
    _save_card_ref_spec(c, nid, ["r1/a1", "r1/a3"])
    c.post(f"/api/newsletters/{nid}/publish")
    from mediahub.email_design import store as ns

    token = ns.newsletter_record("club-a", nid)["public_token"]
    anon = app.test_client()
    assert anon.get(f"/newsletter/{token}/card/r1/a1.png").status_code == 200
    assert anon.get(f"/newsletter/{token}/card/r1/a3.png").status_code == 404
    # editor preview explains the unapproved card instead of a silent blank
    prev = c.get(f"/api/newsletters/{nid}/html?preview=1").get_data(as_text=True)
    assert "data:image/svg+xml;base64," in prev


def test_ai_generation_is_governed_and_metered(app_env, monkeypatch):
    """1.23 governance: an AI newsletter draft is metered against the org and
    hard-blocked at the quota; data-only builds spend nothing."""
    from unittest import mock

    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    monkeypatch.setenv("MEDIAHUB_QUOTA_CAPTION", "1")
    from mediahub.email_design.models import new_newsletter

    spec = new_newsletter("AI draft", "monthly_roundup", brand_profile_id="club-a")
    with mock.patch("mediahub.email_design.draft.generate_newsletter", return_value=spec):
        r1 = _generate(c, with_ai=True)
        assert r1.status_code == 200 and r1.get_json()["ok"] is True
        from mediahub.observability import feature_quota

        assert feature_quota.count_for_org("club-a", feature="caption") == 1
        # over quota → honest block before any provider call
        r2 = _generate(c, with_ai=True)
        assert r2.status_code == 429
        assert r2.get_json()["error"] == "quota_reached"
    # a data-only build is not AI spend: never gated, never metered
    r3 = _generate(c, with_ai=False)
    assert r3.get_json()["ok"] is True
    from mediahub.observability import feature_quota

    assert feature_quota.count_for_org("club-a", feature="caption") == 1


def test_create_hub_shows_newsletter_tile(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    r = c.get("/make")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Open newsletters" in html
    assert "/newsletters" in html


def test_mutating_routes_pass_csrf_with_json_content_type(app_env):
    # Under CSRF enforcement (production), the publish/delete writes must use the
    # JSON content-type to be exempt — which is exactly what the editor JS sends.
    app, wm, tmp = app_env
    app.config["ENFORCE_CSRF"] = True
    c = app.test_client()
    _login(c)
    nid = _generate(c).get_json()["newsletter_id"]  # generate already sends JSON
    # a form-style POST (no JSON content-type) is rejected…
    assert c.post(f"/api/newsletters/{nid}/publish").status_code == 403
    # …and the JSON-content-type write the editor button sends is accepted.
    ok = c.post(f"/api/newsletters/{nid}/publish", headers={"Content-Type": "application/json"})
    assert ok.status_code == 200 and ok.get_json()["ok"] is True


def test_send_button_is_disabled_export_first(app_env):
    app, wm, tmp = app_env
    c = app.test_client()
    _login(c)
    nid = _generate(c).get_json()["newsletter_id"]
    html = c.get(f"/newsletters/{nid}").get_data(as_text=True)
    # the Send affordance is present but honestly disabled (no machine send path)
    assert "Send (coming soon)" in html
    assert "disabled" in html
