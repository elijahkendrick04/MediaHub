"""H-14 — the performance-log form can record platform and which draft.

The manual analytics form posted only type/date/hour/counts even though the
record API accepts `platform` and `pack_id` and the store models both, and
the recent list showed only type + date + score. Now: a platform select
(blank "not sure" default, the shared org platform vocabulary), an optional
"Which draft?" select of this org's recent drafts, query-param prefill for
both (so the draft page's new "Log performance" link lands ready), and the
platform shown in the recent rows.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def client(app):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-a", display_name="Club A"))
    save_profile(ClubProfile(profile_id="club-b", display_name="Club B"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def _save_pack(profile_id="club-a", title_seed="Sam swam a huge PB"):
    from mediahub.club_platform.stub_pack_store import save_pack

    return save_pack(
        "free_text",
        {"free_text": title_seed},
        [{"platform": "Instagram", "caption": "Huge PB!", "confidence": None}],
        profile_id=profile_id,
    )


def test_form_offers_platform_and_draft_selects(client):
    pack = _save_pack()
    html = client.get("/plan/analytics").get_data(as_text=True)
    assert 'id="mh-an-platform"' in html
    assert "Not sure / other" in html
    assert '<option value="instagram"' in html
    assert '<option value="tiktok"' in html
    assert 'id="mh-an-pack"' in html
    assert "Not linked to a draft" in html
    assert f'<option value="{pack["pack_id"]}"' in html
    # The JS payload sends both fields to the record API.
    assert "platform: document.getElementById('mh-an-platform').value" in html
    assert "pack_id: document.getElementById('mh-an-pack').value" in html


def test_foreign_org_drafts_never_listed(client):
    foreign = _save_pack(profile_id="club-b", title_seed="Not our draft at all")
    html = client.get("/plan/analytics").get_data(as_text=True)
    assert foreign["pack_id"] not in html


def test_query_params_prefill_both_selects(client):
    pack = _save_pack()
    html = client.get(
        "/plan/analytics",
        query_string={"pack_id": pack["pack_id"], "platform": "instagram"},
    ).get_data(as_text=True)
    assert '<option value="instagram" selected' in html
    assert f'<option value="{pack["pack_id"]}" selected' in html


def test_recent_rows_show_platform(client):
    from mediahub.analytics.store import record_metric

    record_metric(
        "club-a",
        "free_text",
        "2026-07-01",
        {"likes": 10},
        platform="instagram",
    )
    html = client.get("/plan/analytics").get_data(as_text=True)
    assert "· Instagram" in html


def test_record_api_persists_platform_and_pack(client):
    from mediahub.analytics.store import load_metrics

    pack = _save_pack()
    r = client.post(
        "/api/plan/analytics/record",
        json={
            "post_type": "free_text",
            "posted_date": "2026-07-02",
            "platform": "tiktok",
            "pack_id": pack["pack_id"],
            "metrics": {"likes": 4},
        },
    )
    assert r.status_code == 200 and r.get_json()["ok"] is True
    rows = load_metrics("club-a")
    assert rows and rows[-1].platform == "tiktok"
    assert rows[-1].pack_id == pack["pack_id"]


def test_draft_page_links_to_log_performance(client):
    pack = _save_pack()
    view = client.get(f"/drafts/{pack['pack_id']}").get_data(as_text=True)
    assert "Log performance" in view
    assert f"/plan/analytics?pack_id={pack['pack_id']}" in view
