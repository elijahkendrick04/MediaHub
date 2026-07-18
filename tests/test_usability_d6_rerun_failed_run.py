"""D-6 — a failed pipeline run must not force a full re-upload, nor leak the raw
internal error to customers on the server-rendered failure page.

The launch file is persisted beside every run (input.bin + resume.json), so a
poolside volunteer whose phone no longer has the file can re-run in one click.
And the server-rendered failure page used to print the raw pipeline exception in
a <pre> with no dev gate — this keeps that operator-only.
"""

from __future__ import annotations

import json

import pytest

ORG = "org-test"
LEAK = "SECRET_TRACEBACK_boom_d6"


@pytest.fixture
def env(web_module, client, tmp_path):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Test Club"))
    assert client.post("/api/organisation/active", data={"profile_id": ORG}).status_code == 200
    return {"client": client, "wm": web_module, "tmp": tmp_path}


def _seed_failed_run(env, run_id, *, with_input=True):
    runs_dir = env["tmp"] / "runs_v4"
    (runs_dir / f"{run_id}.json").write_text(json.dumps({"run_id": run_id, "profile_id": ORG}))
    conn = env["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name, error) "
        "VALUES (?, datetime('now'), 'error', ?, ?, ?, ?)",
        (run_id, ORG, "Spring Gala", "spring.hy3", f"Traceback... {LEAK}"),
    )
    conn.commit()
    conn.close()
    if with_input:
        d = runs_dir / run_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "input.bin").write_bytes(b"fake meet bytes")
        (d / "resume.json").write_text(
            json.dumps(
                {
                    "file_name": "spring.hy3",
                    "profile_id": ORG,
                    "use_pb_cache": True,
                    "fetch_pbs": True,
                    "club_filter": "Test Club",
                }
            )
        )


def test_failure_page_hides_raw_error_and_offers_rerun(env):
    _seed_failed_run(env, "runfail0001")
    html = env["client"].get("/runs/runfail0001").get_data(as_text=True)
    # Raw exception is operator-only — a customer never sees it.
    assert LEAK not in html
    assert "Error detail" not in html
    # One-click re-run from the saved file is offered, ahead of re-upload.
    assert "Run this file again" in html
    assert "/runs/runfail0001/rerun" in html


def test_rerun_relaunches_from_saved_file(env, monkeypatch):
    _seed_failed_run(env, "runfail0002")
    captured = {}

    def fake_start_run(*, file_bytes, file_name, profile_id, use_pb_cache, fetch_pbs, club_filter):
        captured.update(
            file_bytes=file_bytes,
            file_name=file_name,
            profile_id=profile_id,
            club_filter=club_filter,
        )
        return "newrun00001"

    monkeypatch.setattr(env["wm"], "_start_run", fake_start_run)
    r = env["client"].post("/runs/runfail0002/rerun", headers={"Accept": "application/json"})
    assert r.status_code == 200
    body = r.get_json()
    assert body["run_id"] == "newrun00001"
    assert "/runs/newrun00001" in body["redirect"]
    # Re-launched from the persisted bytes + saved launch params.
    assert captured["file_bytes"] == b"fake meet bytes"
    assert captured["file_name"] == "spring.hy3"
    assert captured["club_filter"] == "Test Club"


def test_rerun_without_saved_input_is_honest(env):
    _seed_failed_run(env, "runfail0003", with_input=False)
    r = env["client"].post("/runs/runfail0003/rerun", headers={"Accept": "application/json"})
    assert r.status_code == 409
    assert r.get_json()["error"] == "no_saved_input"


def test_failed_runs_appear_in_recent_rerun_list(env):
    _seed_failed_run(env, "runfail0004")
    html = env["client"].get("/upload").get_data(as_text=True)
    # A failed run whose file is on disk shows in "Re-run a recent meet",
    # flagged as not finished, with a retry CTA.
    assert "Re-run a recent meet" in html
    assert "Didn't finish" in html
