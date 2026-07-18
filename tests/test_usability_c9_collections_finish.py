"""C-9 — finish Collections: reachable, fillable, with clickable contents.

/collections was fully built but had zero inbound links and no "add to
collection" action, so every collection stayed at 0 items forever. Now: a
Collections entry link on My Season, clickable collection rows → a detail page
that lists contents (meets resolved to names, linking into review) and offers a
meet picker to add/remove items.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app_env(web_module, monkeypatch):
    # MEDIAHUB_SCHEDULER is read fresh by mediahub.scheduler._enabled() each time
    # start_scheduler() runs inside create_app() — no reload needed for it to take
    # effect, so it's set here, before create_app() is called below.
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(profile_id="club-a", display_name="Riverside SC", brand_voice_summary="x")
    )
    return web_module


def _client(wm):
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-a"
    return c


def _seed_run(wm, rid="run-1", meet="County Champs"):
    conn = wm._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, error) "
        "VALUES (?, datetime('now'), datetime('now'), 'done', 'club-a', ?, 'm.pdf', 3, 0, 0, 8, NULL)",
        (rid, meet),
    )
    conn.commit()
    conn.close()


def test_my_season_links_to_collections(app_env):
    wm = app_env
    _seed_run(wm)  # season needs ≥1 run to show the populated hero
    c = _client(wm)
    html = c.get("/season").get_data(as_text=True)
    assert "/collections" in html
    assert "Collections" in html


def test_collection_row_is_clickable(app_env):
    wm = app_env
    c = _client(wm)
    from mediahub.collab import collections as _col

    col = _col.create_collection("club-a", "Autumn season")
    html = c.get("/collections").get_data(as_text=True)
    assert f"/collections/{col['id']}" in html  # name/Open links into the detail


def test_detail_page_add_and_remove_meet(app_env):
    wm = app_env
    _seed_run(wm, rid="run-x", meet="Spring Open")
    c = _client(wm)
    from mediahub.collab import collections as _col

    col = _col.create_collection("club-a", "Championships")
    cid = col["id"]

    # The detail page offers the meet in its picker (nothing added yet).
    html = c.get(f"/collections/{cid}").get_data(as_text=True)
    assert "Add a meet" in html
    assert "Spring Open" in html
    assert "add a meet below" in html  # empty-contents hint

    # Add the meet via the API the picker posts to.
    r = c.post(
        f"/api/collections/{cid}",
        json={"action": "add_item", "item_type": "run", "item_id": "run-x"},
    )
    assert r.status_code == 200 and r.get_json()["ok"] is True
    items = _col.list_items("club-a", cid)
    assert items and items[0]["item_id"] == "run-x"

    # Now the detail page lists it with a link into review.
    html2 = c.get(f"/collections/{cid}").get_data(as_text=True)
    assert "Spring Open" in html2
    assert "/review/run-x" in html2

    # Remove it.
    r2 = c.post(
        f"/api/collections/{cid}",
        json={"action": "remove_item", "item_type": "run", "item_id": "run-x"},
    )
    assert r2.status_code == 200
    assert _col.list_items("club-a", cid) == []


def test_detail_page_tenant_isolation(app_env):
    wm = app_env
    c = _client(wm)
    from mediahub.collab import collections as _col

    # A collection owned by another org is not viewable.
    other = _col.create_collection("club-b", "Theirs")
    r = c.get(f"/collections/{other['id']}")
    assert "Collection not found" in r.get_data(as_text=True)
