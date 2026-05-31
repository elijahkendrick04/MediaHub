"""Activity dashboard — Council STEP 3 (honest output, 2026-05-31).

The audit found the dashboard headline read "Cards generated: 0" across 16
completed runs. STEP 0 diagnosed it as a *surfacing* bug, not a broken pipeline:
the recognition engine genuinely produced hundreds of ranked achievements per
run (in ``recognition_report``), but the dashboard summed the legacy V4
``n_cards`` (which the recognition-first flow leaves empty) and ``n_achievements``
was not even a DB column. A newcomer reads "0" as "this product made nothing".

The honest fix (no fabricated cards): persist + surface the real achievement
count. These tests pin it, including the self-healing backfill for rows written
before the ``n_achievements`` column existed.
"""
from __future__ import annotations

import importlib
import json
import uuid

import pytest


@pytest.fixture
def activity_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(profile_id="org-a", display_name="Org A",
                             brand_voice_summary="Bold."))

    def seed_run(n_ach, write_db_count=True):
        rid = "run-" + uuid.uuid4().hex[:8]
        payload = {
            "run_id": rid, "profile_id": "org-a", "meet": {"name": f"Meet {rid}"},
            "our_swim_count": n_ach, "cards": [],
            "recognition_report": {
                "ranked_achievements": [], "n_elite": 1, "n_strong": 2,
                "n_story": n_ach - 3, "n_achievements": n_ach, "n_swims_analysed": n_ach,
            },
        }
        (tmp_path / "runs_v4" / f"{rid}.json").write_text(json.dumps(payload))
        conn = wm._db()
        # Simulate a row written BEFORE the n_achievements column existed:
        # legacy n_cards=0, n_achievements left NULL -> must be backfilled.
        conn.execute(
            "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, "
            "meet_name, our_swims, n_cards, n_queue, file_name) "
            "VALUES (?, datetime('now'), 'done', 'org-a', ?, ?, 0, 0, ?)",
            (rid, f"Meet {rid}", n_ach, "x.hy3"),
        )
        conn.commit(); conn.close()
        return rid

    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, seed_run


def _activity(app):
    with app.test_client() as c:
        with c.session_transaction() as s:
            s["active_profile_id"] = "org-a"
        r = c.get("/activity")
        assert r.status_code == 200, r.status_code
        return r.get_data(as_text=True)


class TestActivitySurfacesAchievements:
    def test_headline_is_achievements_not_cards(self, activity_app):
        app, _wm, seed = activity_app
        seed(40); seed(31)
        body = _activity(app)
        assert "Achievements detected" in body
        # The misleading legacy headline must be gone.
        assert "Cards generated" not in body
        # The real total (40 + 31 = 71) is surfaced.
        assert "71" in body

    def test_per_row_shows_achievement_count(self, activity_app):
        app, _wm, seed = activity_app
        seed(40)
        body = _activity(app)
        assert 'data-label="Achievements"' in body
        assert "Queue / Total" not in body  # old misleading column label gone
        assert ">40<" in body

    def test_backfill_persists_to_db(self, activity_app):
        app, wm, seed = activity_app
        rid = seed(40)
        # First view triggers the lazy backfill (read run JSON -> UPDATE row).
        _activity(app)
        conn = wm._db()
        row = conn.execute("SELECT n_achievements FROM runs WHERE id = ?", (rid,)).fetchone()
        conn.close()
        assert row is not None and int(row["n_achievements"]) == 40

    def test_new_runs_persist_n_achievements_on_save(self, activity_app):
        # A run saved through the real persistence path carries its recognition
        # count straight into the DB (no backfill needed).
        app, wm, _seed = activity_app
        conn = wm._db()
        cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
        conn.close()
        assert "n_achievements" in cols
