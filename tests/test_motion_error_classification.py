"""tests/test_motion_error_classification.py — Phase 1.5 UX fix.

When Remotion rendering fails (because the operator's Docker build
silently skipped npm install, or because we're in a dev env), the
API used to surface the raw Node module-not-found stack trace
verbatim. Users saw "Cannot find module @remotion/bundler" in the UI.

The fix: classify the underlying RuntimeError into one of three
known kinds (``infra_missing`` / ``timeout`` / ``internal``) and
attach a ``user_message`` field with operator-written copy. The
frontend JS prefers that field.

These tests pin:
  * The classification function maps known error strings correctly.
  * The route returns the right kind + user_message for each class.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="t", display_name="T", brand_voice_summary="Friendly.",
    ))
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "t"})
        yield c, app, tmp_path


def _seed_minimal_run(tmp_path: Path) -> str:
    """Drop a minimal run.json so the motion route's run-lookup
    succeeds. We don't need real card payloads — the patched motion
    function raises before they're consumed."""
    import json
    import sqlite3
    import uuid
    run_id = uuid.uuid4().hex[:12]
    run_dir = tmp_path / "runs_v4" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "cards": [{
            "swim_id": "alpha", "id": "alpha",
            "result": {}, "athlete": {},
        }],
        "recognition_report": {
            "ranked_achievements": [{
                "achievement": {"swim_id": "alpha"},
                "id": "alpha",
            }],
        },
    }
    (run_dir / "run.json").write_text(json.dumps(payload))
    # Plus the legacy <id>.json layout some loaders expect.
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(payload))
    # And a DB row so /activity etc. don't trip.
    conn = sqlite3.connect(str(tmp_path / "data.db"))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created_at TEXT, "
        "finished_at TEXT, status TEXT, profile_id TEXT, meet_name TEXT, "
        "our_swims INTEGER, n_cards INTEGER, n_queue INTEGER, error TEXT, file_name TEXT)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, profile_id, status) VALUES (?, ?, 'done')",
        (run_id, "t"),
    )
    conn.commit()
    conn.close()
    return run_id


class TestMotionErrorClassification:
    def test_infra_missing_returns_user_friendly_copy(self, gated_app):
        c, app, tmp_path = gated_app
        run_id = _seed_minimal_run(tmp_path)

        # Patch the motion module so it raises the exact error class
        # we want to translate.
        with patch("mediahub.visual.motion.render_story_card") as render:
            render.side_effect = RuntimeError(
                "Remotion render failed (exit 3):\n"
                "Cannot find module '@remotion/bundler'\n"
                "Require stack:\n- /app/src/mediahub/remotion/render.js"
            )
            resp = c.post(f"/api/runs/{run_id}/card/alpha/motion")

        assert resp.status_code == 500
        body = resp.get_json() or {}
        assert body.get("error") == "render_failed"
        assert body.get("kind") == "infra_missing"
        # User-friendly copy:
        assert "isn't available on this deployment" in body.get("user_message", "")
        assert "operator" in body.get("user_message", "").lower()
        # Detail kept for ops debugging:
        assert "Cannot find module" in body.get("detail", "")

    def test_timeout_returns_timeout_kind(self, gated_app):
        c, app, tmp_path = gated_app
        run_id = _seed_minimal_run(tmp_path)
        with patch("mediahub.visual.motion.render_story_card") as render:
            render.side_effect = RuntimeError("Remotion render timed out after 90s")
            resp = c.post(f"/api/runs/{run_id}/card/alpha/motion")

        body = resp.get_json() or {}
        assert body.get("kind") == "timeout"
        assert "too long" in body.get("user_message", "").lower()

    def test_unknown_failure_falls_through_to_internal(self, gated_app):
        c, app, tmp_path = gated_app
        run_id = _seed_minimal_run(tmp_path)
        with patch("mediahub.visual.motion.render_story_card") as render:
            render.side_effect = RuntimeError("Some weird thing happened")
            resp = c.post(f"/api/runs/{run_id}/card/alpha/motion")

        body = resp.get_json() or {}
        assert body.get("kind") == "internal"
        # The detail still preserves the raw error.
        assert "Some weird thing" in body.get("detail", "")
        # And the user_message is generic but actionable.
        assert "Create graphic" in body.get("user_message", "")
