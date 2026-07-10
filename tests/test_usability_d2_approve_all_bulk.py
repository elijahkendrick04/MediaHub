"""D-2 — "Approve all in queue" must approve every queued card in ONE bulk
request, not fire one POST + one toast per card.

The old handler did ``queued.forEach(... btn.click())`` — on a 150–250 card meet
that launched 150+ concurrent fetches and stacked up to 150 success toasts,
with no aggregate result and any failure reverting silently. A single-request
bulk endpoint (``api_cards_bulk_status``) that returns per-card gate results
already exists and is used by the neighbouring bulk bar. This guards that
"Approve all in queue" makes exactly ONE bulk POST.

J-3 update: the review list is now paginated server-side, so the handler no
longer ticks the visible rows' checkboxes (that would approve only the current
page). It reads the server-embedded FULL queued-id list (``#mh-queued-ids``)
and POSTs it to ``api_cards_bulk_status`` in one request — same single-POST
intent, now covering the whole queue.
"""

from __future__ import annotations

import importlib
import json
import uuid

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="org-test", display_name="Test Club"))
    app = wm.create_app()
    app.config["TESTING"] = True
    c = app.test_client()
    assert c.post("/api/organisation/active", data={"profile_id": "org-test"}).status_code == 200
    return {"client": c, "wm": wm, "tmp": tmp_path}


def _seed_run(env, swim_ids):
    run_id = "run-d2-" + uuid.uuid4().hex[:8]
    payload = {
        "run_id": run_id,
        "profile_id": "org-test",
        "meet": {"name": "D2 BULK TEST"},
        "cards": [{"card_id": f"card-{s}", "swim_id": s, "id": f"card-{s}"} for s in swim_ids],
        "recognition_report": {
            "ranked_achievements": [
                {
                    "rank": i + 1,
                    "achievement": {
                        "swim_id": s,
                        "swimmer_name": f"Swimmer {i}",
                        "event": "100 Free",
                        "headline": f"PB for Swimmer {i}",
                        "type": "pb",
                        "confidence_label": "high",
                    },
                    "quality_band": "elite",
                    "priority": 0.9,
                    "suggested_post_type": "story",
                    "factors": [],
                }
                for i, s in enumerate(swim_ids)
            ],
            "n_achievements": len(swim_ids),
        },
    }
    (env["tmp"] / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    conn = env["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', 'org-test', ?, ?)",
        (run_id, "D2 BULK TEST", "test.hy3"),
    )
    conn.commit()
    conn.close()
    return run_id


def test_approve_all_routes_through_single_post_bulk_bar(env):
    run_id = _seed_run(env, ["s1", "s2", "s3"])
    html = env["client"].get(f"/review/{run_id}").get_data(as_text=True)
    # One request, one summary toast: the handler reads the server-embedded
    # full queued-id list and fires a single JSON POST to the bulk endpoint
    # (J-3 replaced the old tick-the-visible-checkboxes path, which under
    # pagination would only ever approve the current page).
    assert "mh-review-bulk" in html
    assert '<script type="application/json" id="mh-queued-ids">' in html
    assert f"/api/runs/{run_id}/cards/bulk-status" in html
    assert "JSON.stringify({ids: ids, status: 'approved'})" in html
    # The legacy per-card / per-page paths are gone.
    assert "approveBtn.click()" not in html
    assert "Approving ' + n + ' card" not in html


def test_bulk_endpoint_approves_many_in_one_request(env):
    run_id = _seed_run(env, ["s1", "s2", "s3"])
    ids = ["card-s1", "card-s2", "card-s3"]
    r = env["client"].post(
        f"/api/runs/{run_id}/cards/bulk-status",
        json={"ids": ids, "status": "approved"},
        headers={"Accept": "application/json"},
    )
    assert r.status_code == 200
    body = r.get_json()
    # One response carrying a per-card result list — the summary toast source.
    results = body.get("results")
    assert isinstance(results, list)
    assert {r_["id"] for r_ in results} == set(ids)
    assert all(r_.get("ok") for r_ in results)
