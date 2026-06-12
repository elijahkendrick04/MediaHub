"""tests/test_upload_pins_active_profile.py — Phase 1.5 org-scoping fix.

When a user uploads a meet file through the org-gated Create flow,
the resulting run MUST be tagged with their active organisation's
profile_id. Without this, the run finishes successfully but never
appears on /activity (which is profile-scoped) — leading the user to
think their upload disappeared.

This file pins the fix: after configure POST, the run row in the
SQLite ``runs`` table has ``profile_id`` == the active session profile.
"""
from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="wycombe",
        display_name="Wycombe District Swimming Club",
        brand_voice_summary="A friendly club.",
    ))
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "wycombe"})
        yield c, app, tmp_path


class TestRunPinsActiveProfile:
    def test_configure_post_tags_run_with_active_profile(self, gated_client):
        """The configure POST must persist the active profile_id into
        the runs row so the run shows on /activity."""
        c, _, tmp_path = gated_client
        sample = Path(__file__).resolve().parents[1] / "sample_data" / "MISM-2024-Results.pdf"
        if not sample.exists():
            pytest.skip(f"sample missing: {sample}")

        # Step 1: upload a real meet file.
        with sample.open("rb") as f:
            resp = c.post(
                "/upload",
                data={"file": (io.BytesIO(f.read()), "MISM-2024-Results.pdf")},
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        assert resp.status_code == 302
        # Extract the temp run_id from the redirect.
        loc = resp.headers.get("Location", "")
        assert "run_id=" in loc
        run_id = loc.split("run_id=", 1)[1]

        # Step 2: submit the configure POST.
        resp = c.post(
            "/upload/configure",
            data={
                "run_id": run_id,
                "club_filter": "Co Manch Aq",
                "primary_colour": "#002640",
                "secondary_colour": "#00855b",
                "accent_colour": "#FFD86E",
                "use_logo_colours": "false",
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )
        assert resp.status_code == 302
        new_run_id = resp.headers.get("Location", "").rsplit("/", 1)[-1]
        assert new_run_id and len(new_run_id) >= 8

        # Step 3: the runs DB row must now carry profile_id = "wycombe".
        import sqlite3
        conn = sqlite3.connect(str(tmp_path / "data.db"))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, profile_id, status FROM runs WHERE id = ?",
            (new_run_id,),
        ).fetchone()
        conn.close()
        assert row is not None, f"run {new_run_id} not in DB"
        assert row["profile_id"] == "wycombe", (
            f"run was tagged with profile_id={row['profile_id']!r}, "
            f"expected 'wycombe' — /activity won't show it"
        )

    def test_activity_page_shows_run_after_configure(self, gated_client):
        """End-to-end: a run created by the active org should appear on
        /activity. Without the profile_id fix, the activity page is
        empty even when the DB has the row."""
        c, _, _ = gated_client
        sample = Path(__file__).resolve().parents[1] / "sample_data" / "MISM-2024-Results.pdf"
        if not sample.exists():
            pytest.skip(f"sample missing: {sample}")

        with sample.open("rb") as f:
            up_resp = c.post(
                "/upload",
                data={"file": (io.BytesIO(f.read()), "MISM-2024-Results.pdf")},
                content_type="multipart/form-data",
                follow_redirects=False,
            )
        run_id = up_resp.headers["Location"].split("run_id=", 1)[1]
        c.post(
            "/upload/configure",
            data={
                "run_id": run_id,
                "club_filter": "Co Manch Aq",
                "primary_colour": "#002640",
                "secondary_colour": "#000000",
                "accent_colour": "#FFD86E",
                "use_logo_colours": "false",
            },
            content_type="multipart/form-data",
            follow_redirects=False,
        )

        # The activity page should NOT render the empty state.
        resp = c.get("/activity")
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "No runs yet for this organisation" not in body, (
            "activity page shows empty state even though we just ran a "
            "successful upload for the active org"
        )
        # And the file name should be on the page.
        assert "MISM-2024-Results.pdf" in body
