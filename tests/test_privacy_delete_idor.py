"""Security regression: /privacy/run/<id>/delete is per-tenant.

Pre-fix, anyone with a session could delete any run by guessing or
knowing its 12-char hex id, regardless of which organisation owned it.
The fix on `privacy_delete_run` looks up the run's `profile_id` in the
DB and compares against the active session profile, returning 404 if
they don't match.

This test seeds two organisations with one run each, signs in as
tenant A, and asserts that A cannot delete B's run.
"""
from __future__ import annotations

import importlib
import json
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
    for pid, name in (("club-a", "Club A"), ("club-b", "Club B")):
        save_profile(ClubProfile(
            profile_id=pid, display_name=name,
            brand_voice_summary=f"{name} voice.",
        ))

    # Seed one run per club, both on disk and in the DB so _delete_run
    # has something to clean up if the guard is missing.
    runs_dir = tmp_path / "runs_v4"
    for run_id, pid, meet in (
        ("run-a-001", "club-a", "Club A meet"),
        ("run-b-001", "club-b", "Club B meet"),
    ):
        (runs_dir / f"{run_id}.json").write_text(json.dumps({
            "run_id": run_id, "profile_id": pid, "meet_name": meet,
        }))
        conn = wm._db()
        conn.execute(
            "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
            "meet_name, file_name, our_swims, n_cards, n_queue, error) "
            "VALUES (?, datetime('now'), datetime('now'), 'done', ?, ?, 'f.hy3', "
            "1, 1, 0, NULL)",
            (run_id, pid, meet),
        )
        conn.commit(); conn.close()

    with app.test_client() as c:
        yield c, app, tmp_path


def _pin(c, profile_id: str) -> None:
    resp = c.post("/api/organisation/active", data={"profile_id": profile_id})
    assert resp.status_code == 200, resp.get_json()


def _run_in_db(wm, run_id: str) -> bool:
    conn = wm._db()
    n = conn.execute("SELECT COUNT(*) FROM runs WHERE id = ?", (run_id,)).fetchone()[0]
    conn.close()
    return bool(n)


def test_owner_can_delete_own_run(gated_client):
    c, _, tmp = gated_client
    import mediahub.web.web as wm
    _pin(c, "club-a")
    assert (tmp / "runs_v4" / "run-a-001.json").exists()
    resp = c.post("/privacy/run/run-a-001/delete", follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert not (tmp / "runs_v4" / "run-a-001.json").exists()
    assert not _run_in_db(wm, "run-a-001")


def test_other_tenant_cannot_delete_run(gated_client):
    c, _, tmp = gated_client
    import mediahub.web.web as wm
    _pin(c, "club-a")
    # Confirm pre-state: B's run exists
    assert (tmp / "runs_v4" / "run-b-001.json").exists()
    assert _run_in_db(wm, "run-b-001")
    resp = c.post("/privacy/run/run-b-001/delete", follow_redirects=False)
    assert resp.status_code == 404
    # B's run still intact on disk AND in DB
    assert (tmp / "runs_v4" / "run-b-001.json").exists()
    assert _run_in_db(wm, "run-b-001")


def test_malformed_run_id_returns_400(gated_client):
    c, _, _ = gated_client
    _pin(c, "club-a")
    # Slash is blocked by Flask's string converter so this 404s at
    # routing time; backslashes / dots are allowed by the converter but
    # rejected by the regex guard.
    resp = c.post("/privacy/run/..something/delete", follow_redirects=False)
    assert resp.status_code == 400


def test_nonexistent_run_returns_404(gated_client):
    c, _, _ = gated_client
    _pin(c, "club-a")
    resp = c.post("/privacy/run/never-existed/delete", follow_redirects=False)
    assert resp.status_code == 404
