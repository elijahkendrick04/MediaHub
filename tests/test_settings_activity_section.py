"""tests/test_settings_activity_section.py — the Settings > Activity page.

The Settings "Activity" card (``/settings/activity``) is the per-organisation
run log: "Every run for this organisation — status, matches, and one-click
delete." It is a distinct surface from the standalone ``/activity`` page and is
rendered by ``_render_settings_activity_section``.

These tests lock the behaviour fixed in the Activity feature audit:

  * The table surfaces the REAL engine output (V5 recognition *achievements*),
    NOT the legacy ``n_cards`` / ``n_queue`` counts which the recognition-first
    pipeline leaves at 0 — a modern run must not read as "0 / 0 produced
    nothing". (Regression: the standalone /activity page was fixed for this but
    the Settings mirror was not.)
  * Tenant isolation: a pinned org only ever sees its own runs.
  * User-controlled meet names are HTML-escaped (no stored XSS).
  * Each per-row Delete control carries a descriptive ``aria-label`` so screen
    readers can tell the buttons apart.
  * The "N runs failed" callout counts every errored run, even one with no
    captured error text (which still shows a red "error" badge).
  * The 100-run cap is disclosed honestly when older runs exist.
  * A runs-store read failure surfaces an honest error, not a misleading
    "no results yet" empty state.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def activity_client(tmp_path, monkeypatch):
    """Fresh DATA_DIR with the org gate enforced; two orgs + seeded runs.

    Reloads the web module so module-level DB_PATH / RUNS_DIR re-resolve
    against tmp_path (mirrors tests/test_activity_scoping.py)."""
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

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="club-a", display_name="Club A", brand_voice_summary="A friendly club."
        )
    )
    save_profile(
        ClubProfile(
            profile_id="club-b", display_name="Club B", brand_voice_summary="A serious club."
        )
    )

    with app.test_client() as c:
        yield c, wm


def _seed(wm, rows):
    """rows: (id, profile_id, meet, status, our_swims, n_cards, n_queue,
    n_achievements, error)."""
    conn = wm._db()
    for rid, pid, meet, status, sw, nc, nq, nach, err in rows:
        conn.execute(
            "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
            "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, error) "
            "VALUES (?, datetime('now'), datetime('now'), ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (rid, status, pid, meet, f"{meet}.pdf", sw, nc, nq, nach, err),
        )
    conn.commit()
    conn.close()


def _pin(client, profile_id):
    resp = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert resp.status_code == 200, resp.get_json()


def _get(client, profile_id="club-a"):
    _pin(client, profile_id)
    resp = client.get("/settings/activity")
    assert resp.status_code == 200
    return resp.get_data(as_text=True)


# ---------------------------------------------------------------------------
# 1. The REAL engine output (achievements), not legacy 0/0 counts
# ---------------------------------------------------------------------------


class TestAchievementsColumn:
    def test_shows_achievements_not_legacy_queue_total(self, activity_client):
        c, wm = activity_client
        # A modern V5 run: real achievements, but n_cards/n_queue left at 0.
        _seed(
            c and wm,
            [
                ("v5run000001", "club-a", "Summer Open", "done", 30, 0, 0, 7, None),
            ],
        )
        body = _get(c)
        # The column header is Achievements, and the legacy label is gone.
        assert "Achievements" in body
        assert "Queue / Total" not in body
        # The real count is displayed for the run (was "0 / 0" before the fix).
        row = body[body.find('data-run-row="v5run000001"') :]
        row = row[: row.find("</tr>")]
        assert '<td data-label="Achievements">7</td>' in row

    def test_matched_column_still_shows_our_swims(self, activity_client):
        c, wm = activity_client
        _seed(
            c and wm,
            [
                ("v5run000002", "club-a", "County Champs", "done", 42, 0, 0, 12, None),
            ],
        )
        body = _get(c)
        row = body[body.find('data-run-row="v5run000002"') :]
        row = row[: row.find("</tr>")]
        assert '<td data-label="Matched">42</td>' in row


# ---------------------------------------------------------------------------
# 2. Tenant isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    def test_only_active_org_runs_appear(self, activity_client):
        c, wm = activity_client
        _seed(
            c and wm,
            [
                ("aaa000000001", "club-a", "Club A Meet", "done", 1, 0, 0, 1, None),
                ("bbb000000001", "club-b", "Club B Secret", "done", 1, 0, 0, 1, None),
            ],
        )
        body = _get(c, "club-a")
        assert "Club A Meet" in body
        assert "Club B Secret" not in body

    def test_empty_state_for_org_with_no_runs(self, activity_client):
        c, wm = activity_client
        _seed(
            c and wm,
            [
                ("bbb000000002", "club-b", "Club B Meet", "done", 1, 0, 0, 1, None),
            ],
        )
        body = _get(c, "club-a")
        assert "No results yet for this organisation" in body
        assert "Club B Meet" not in body


# ---------------------------------------------------------------------------
# 3. XSS escaping
# ---------------------------------------------------------------------------


class TestXssEscaping:
    def test_meet_name_script_is_escaped(self, activity_client):
        c, wm = activity_client
        _seed(
            c and wm,
            [
                (
                    "xss000000001",
                    "club-a",
                    "Winter <script>alert(1)</script>",
                    "done",
                    1,
                    0,
                    0,
                    1,
                    None,
                ),
            ],
        )
        body = _get(c)
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body


# ---------------------------------------------------------------------------
# 4. Accessible per-row Delete controls
# ---------------------------------------------------------------------------


class TestDeleteAffordance:
    def test_delete_button_has_descriptive_aria_label(self, activity_client):
        c, wm = activity_client
        _seed(
            c and wm,
            [
                ("del000000001", "club-a", "Named Meet", "done", 1, 0, 0, 1, None),
            ],
        )
        body = _get(c)
        assert 'aria-label="Delete Named Meet"' in body

    def test_delete_form_targets_privacy_delete_route(self, activity_client):
        c, wm = activity_client
        _seed(
            c and wm,
            [
                ("del000000002", "club-a", "Deletable", "done", 1, 0, 0, 1, None),
            ],
        )
        body = _get(c)
        assert 'action="/privacy/run/del000000002/delete"' in body
        # The no-JS fallback returns the user to this page.
        assert 'name="next" value="/settings/activity"' in body


# ---------------------------------------------------------------------------
# 5. Failure callout counts every errored run
# ---------------------------------------------------------------------------


class TestFailureCallout:
    def test_error_run_without_error_text_is_counted(self, activity_client):
        c, wm = activity_client
        # Two errored runs: one with captured text, one with none. Both carry a
        # red "error" badge, so both must be counted in the callout.
        _seed(
            c and wm,
            [
                ("err000000001", "club-a", "Failed A", "error", 0, 0, 0, 0, "boom"),
                ("err000000002", "club-a", "Failed B", "error", 0, 0, 0, 0, None),
            ],
        )
        body = _get(c)
        assert "2 runs failed" in body

    def test_single_failure_is_singular(self, activity_client):
        c, wm = activity_client
        _seed(
            c and wm,
            [
                ("err000000003", "club-a", "Only Fail", "error", 0, 0, 0, 0, None),
            ],
        )
        body = _get(c)
        assert "1 run failed" in body


# ---------------------------------------------------------------------------
# 6. Honest 100-run cap disclosure
# ---------------------------------------------------------------------------


class TestTruncationNotice:
    def test_note_absent_when_under_cap(self, activity_client):
        c, wm = activity_client
        _seed(
            c and wm,
            [(f"cap{i:09d}", "club-a", f"Meet {i}", "done", 1, 0, 0, 1, None) for i in range(5)],
        )
        body = _get(c)
        assert "most recent runs of" not in body

    def test_note_present_when_over_cap(self, activity_client):
        c, wm = activity_client
        _seed(
            c and wm,
            [(f"cap{i:09d}", "club-a", f"Meet {i}", "done", 1, 0, 0, 1, None) for i in range(105)],
        )
        body = _get(c)
        # 105 total, table capped at 100 → an honest "showing 100 of 105" note.
        assert "Showing the 100 most recent runs of 105 total" in body


# ---------------------------------------------------------------------------
# 7. Honest error state on a runs-store failure
# ---------------------------------------------------------------------------


class TestDbFailure:
    def test_db_read_failure_shows_honest_error_not_empty_state(self, activity_client, monkeypatch):
        c, wm = activity_client

        def _boom():
            raise RuntimeError("db unreachable")

        monkeypatch.setattr(wm, "_db", _boom)
        _pin(c, "club-a")
        resp = c.get("/settings/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "Couldn&rsquo;t reach the runs store" in body
        # Must NOT masquerade a store failure as a genuinely empty org.
        assert "No results yet for this organisation" not in body
