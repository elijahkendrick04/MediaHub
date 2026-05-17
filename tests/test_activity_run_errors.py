"""tests/test_activity_run_errors.py — Phase 1.5 "Why did this run fail?".

Pins the per-run pipeline error surfacing on /activity:

  * Errored runs render a collapsible "Why did this run fail?" block
    immediately under their row that contains the persisted error text.
  * Successful runs do NOT render the error block.
  * The header callout counts how many of the most-recent 100 runs failed.
  * Long error texts are truncated to keep the table compact.
"""
from __future__ import annotations

import importlib
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
        profile_id="club-a", display_name="Club A",
        brand_voice_summary="A friendly club.",
    ))
    with app.test_client() as c:
        yield c, app


def _pin(client, profile_id: str) -> None:
    resp = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert resp.status_code == 200


def _seed_run(*, run_id: str, profile_id: str, meet: str,
              status: str = "done", error: str = None) -> None:
    import mediahub.web.web as wm
    conn = wm._db()
    conn.execute(
        "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, file_name, our_swims, n_cards, n_queue, error) "
        "VALUES (?, datetime('now'), datetime('now'), ?, ?, ?, ?, 1, 1, 0, ?)",
        (run_id, status, profile_id, meet, f"{meet}.pdf", error),
    )
    conn.commit()
    conn.close()


class TestErrorRowSurfacing:
    def test_no_failure_callout_when_all_runs_ok(self, gated_client):
        c, _ = gated_client
        _seed_run(run_id="run-1", profile_id="club-a", meet="OK meet")
        _pin(c, "club-a")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        assert "Why did this run fail?" not in body
        assert "runs failed" not in body
        assert "run failed" not in body

    def test_errored_run_renders_collapsible_block_with_error(self, gated_client):
        c, _ = gated_client
        _seed_run(
            run_id="run-bad", profile_id="club-a", meet="Broken meet",
            status="error",
            error="Parse failed: HY3 file is missing event header on row 12",
        )
        _pin(c, "club-a")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        # Header callout is present.
        assert "1 run failed" in body
        # The collapsible block is rendered.
        assert "Why did this run fail?" in body
        # The actual error text appears.
        assert "HY3 file is missing event header on row 12" in body
        # It lives inside a <details> element.
        assert "<details>" in body

    def test_multiple_errored_runs_count_in_callout(self, gated_client):
        c, _ = gated_client
        _seed_run(run_id="r1", profile_id="club-a", meet="ok meet")
        _seed_run(run_id="r2", profile_id="club-a", meet="bad 1",
                  status="error", error="error one")
        _seed_run(run_id="r3", profile_id="club-a", meet="bad 2",
                  status="error", error="error two")
        _pin(c, "club-a")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        assert "2 runs failed" in body
        # Both error messages are listed.
        assert "error one" in body
        assert "error two" in body

    def test_long_error_message_truncated_with_ellipsis(self, gated_client):
        c, _ = gated_client
        long_err = "Traceback line " * 200  # ~3,200 chars
        _seed_run(
            run_id="run-long", profile_id="club-a", meet="Tracebacky",
            status="error", error=long_err,
        )
        _pin(c, "club-a")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        assert "Why did this run fail?" in body
        # Truncation marker present and the giant string is not fully embedded.
        assert "…" in body
        # Should not be the entire 3200-char string in the body.
        assert body.count("Traceback line ") < 200

    def test_error_text_is_html_escaped(self, gated_client):
        """Error text must NEVER be rendered as live HTML — pipeline errors
        can contain arbitrary content from user files."""
        c, _ = gated_client
        _seed_run(
            run_id="run-xss", profile_id="club-a", meet="XSS test",
            status="error",
            error="<script>alert('xss')</script>",
        )
        _pin(c, "club-a")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        # The literal escaped form must appear.
        assert "&lt;script&gt;" in body
        # The unescaped form must NOT.
        assert "<script>alert('xss')</script>" not in body

    def test_errored_run_in_other_org_does_not_leak(self, gated_client):
        """Org scoping invariant — errors from another tenant must NOT
        surface on this tenant's activity page."""
        c, _ = gated_client
        from mediahub.web.club_profile import ClubProfile, save_profile
        save_profile(ClubProfile(
            profile_id="club-b", display_name="Club B",
            brand_voice_summary="Serious club.",
        ))
        _seed_run(
            run_id="r-b-err", profile_id="club-b", meet="club-b meet",
            status="error", error="club-b secret error detail",
        )
        # Seed a club-a run with no errors so the page renders normally.
        _seed_run(run_id="r-a-ok", profile_id="club-a", meet="club-a meet")
        _pin(c, "club-a")
        resp = c.get("/activity")
        body = resp.get_data(as_text=True)
        assert "club-b secret error detail" not in body
        assert "Why did this run fail?" not in body
