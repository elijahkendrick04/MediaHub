"""I-3 & I-5 — compliance tables and the review filter bar on a phone.

I-3: the athlete-rights (7-col, inline action forms) and consent registry
(5-col) tables were non-responsive raw tables that overflowed a narrow screen.
Each is now wrapped in a .mh-table-scroll container.

I-5: the review filter bar (nine controls) was position:sticky and pinned over a
third of the viewport while scrolling on small screens. It's now non-sticky
below 700px.
"""

from __future__ import annotations

import pytest

ORG = "club-a"


@pytest.fixture
def client(app):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Club A"))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = ORG
    return c


def test_athlete_rights_table_wrapped(client):
    html = client.get("/organisation/athlete-rights").get_data(as_text=True)
    assert "mh-table-scroll" in html
    # The rights table columns are still there.
    assert "<th>Due</th>" in html


def test_consent_registry_table_wrapped(client):
    # G-9 moved the registry to /athletes?tab=records; the old URL redirects.
    html = client.get("/organisation/consent", follow_redirects=True).get_data(as_text=True)
    assert "mh-table-scroll" in html


def test_review_filter_bar_non_sticky_on_mobile(client, tmp_path):
    import json

    import mediahub.web.web as wm

    run_id = "runfilter001"
    # Write the run.json to the module's ACTUAL RUNS_DIR rather than a hardcoded
    # tmp_path/runs_v4 — otherwise, if an earlier test in the shard leaves RUNS_DIR
    # resolved elsewhere, /review can't load the run, renders a recovery page
    # without the filter bar, and this assertion flakes (order-dependent).
    wm.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    (wm.RUNS_DIR / f"{run_id}.json").write_text(
        json.dumps(
            {"run_id": run_id, "profile_id": ORG, "meet": {"name": "M"}, "recognition_report": {}}
        )
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', ?, 'M', 's.hy3')",
        (run_id, ORG),
    )
    conn.commit()
    conn.close()
    css = client.get(f"/review/{run_id}").get_data(as_text=True)
    assert "position: static; top: auto" in css
