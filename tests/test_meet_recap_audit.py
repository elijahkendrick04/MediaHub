"""tests/test_meet_recap_audit.py — Meet Recap (Create) audit regressions.

Locks the behaviour fixed in the Meet Recap end-to-end audit
(docs/audits/AUDIT_meet-recap.md):

  * VE-1  — the /upload reject branches return a 4xx, not a 200.
  * CTRL-1 — the "Re-run a recent meet" card's configure link reopens the
             configure step for a persisted run instead of 404ing.
  * CDI-2 — a run persists its club_filter, so the review empty-state can tell
             "no club selected" from "a club matched zero swimmers".
  * UISE-01 — a failed run's /review page keeps the raw exception text
             (absolute paths, exception internals) operator-only.
"""
from __future__ import annotations

import importlib
import io
import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SAMPLE = _ROOT / "samples/learning_corpus/level1/2025_11_nd_open_championships/results_hy3.zip"


@pytest.fixture
def env(tmp_path, monkeypatch):
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
    app.config["TESTING"] = True  # bypass the org-ready gate (conftest convention)

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="cog",
        display_name="City Of Glasgow Swim Team",
        brand_voice_summary="Proud and friendly.",
    ))
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "cog"
    return c, wm


def _run_meet(c, wm, club):
    """Drive upload -> configure -> pipeline offline; return the finished run id."""
    data = _SAMPLE.read_bytes()
    r = c.post("/upload", data={"file": (io.BytesIO(data), "results_hy3.zip")},
               content_type="multipart/form-data")
    tmp = r.headers["Location"].split("run_id=")[-1]
    mp = wm.RUNS_DIR / tmp / "upload_meta.json"
    meta = json.loads(mp.read_text())
    meta["fetch_pbs"] = False  # deterministic offline run, no network PB lookup
    mp.write_text(json.dumps(meta))
    r = c.post(f"/upload/configure?run_id={tmp}", data={"club_filter": club})
    run_id = r.headers["Location"].rstrip("/").rsplit("/", 1)[-1]
    for _ in range(120):
        if c.get(f"/api/runs/{run_id}/status").get_json().get("status") in ("done", "error"):
            break
        time.sleep(1)
    return run_id


# ---------------------------------------------------------------- VE-1
class TestUploadRejectStatus:
    def test_no_file_is_400(self, env):
        c, _ = env
        r = c.post("/upload", data={}, content_type="multipart/form-data")
        assert r.status_code == 400
        assert "No file selected" in r.get_data(as_text=True)

    def test_empty_file_is_400(self, env):
        c, _ = env
        r = c.post("/upload", data={"file": (io.BytesIO(b""), "e.hy3")},
                   content_type="multipart/form-data")
        assert r.status_code == 400
        assert "empty" in r.get_data(as_text=True).lower()

    def test_bad_extension_stays_400(self, env):
        c, _ = env
        r = c.post("/upload", data={"file": (io.BytesIO(b"x"), "b.exe")},
                   content_type="multipart/form-data")
        assert r.status_code == 400


# ---------------------------------------------------------------- CTRL-1
@pytest.mark.skipif(not _SAMPLE.exists(), reason="sample HY3 corpus zip absent")
class TestReconfigurePersistedRun:
    def test_configure_rebuilds_meta_from_saved_input(self, env):
        c, wm = env
        # A persisted run as the "Re-run a recent meet" card leaves it: input.bin
        # + resume.json on disk, but NO staged upload_meta.json.
        rid = "reconftest01"
        d = wm.RUNS_DIR / rid
        d.mkdir(parents=True, exist_ok=True)
        (d / "input.bin").write_bytes(_SAMPLE.read_bytes())
        (d / "resume.json").write_text(json.dumps({
            "file_name": "results_hy3.zip", "profile_id": "cog",
            "use_pb_cache": True, "fetch_pbs": False,
            "club_filter": "City Of Glasgow Swim Team", "source_url": None,
        }))
        assert not (d / "upload_meta.json").exists()
        r = c.get(f"/upload/configure?run_id={rid}")
        assert r.status_code == 200, "re-configure of a persisted run must not 404"
        body = r.get_data(as_text=True)
        assert "Upload session expired" not in body
        # The clubs were re-parsed from the saved bytes and offered again.
        assert "City Of Glasgow Swim Team" in body


# ---------------------------------------------------------------- CDI-2
@pytest.mark.skipif(not _SAMPLE.exists(), reason="sample HY3 corpus zip absent")
class TestClubFilterPersistedAndReported:
    def test_nomatch_run_persists_filter_and_names_it(self, env):
        c, wm = env
        club = "Penguins Underwater Basketweaving Club"  # matches no swimmer
        run_id = _run_meet(c, wm, club)
        rj = json.loads((wm.RUNS_DIR / f"{run_id}.json").read_text())
        # The fix: the pipeline's club_filter is persisted...
        assert rj.get("club_filter") == club
        assert (rj.get("our_swim_count") or 0) == 0
        body = c.get(f"/review/{run_id}").get_data(as_text=True)
        # ...so the review empty-state fires the correct "written differently"
        # branch (naming the club) rather than "no club was selected".
        assert "written differently" in body
        assert club in body
        assert "no club was selected" not in body


# ---------------------------------------------------------------- UISE-01
class TestFailedRunErrorLeak:
    _LEAK = "interpreter failed: /srv/mediahub/data/runs/abc/input.bin missing sheet 'Results'"

    def _write_failed_run(self, wm, run_id):
        (wm.RUNS_DIR / f"{run_id}.json").write_text(json.dumps({
            "run_id": run_id, "profile_id": "cog", "file_name": "x.hy3",
            "error": self._LEAK, "meet": {}, "cards": [],
        }))

    def test_customer_review_hides_raw_exception(self, env):
        c, wm = env
        self._write_failed_run(wm, "errleak_cust")
        body = c.get("/review/errleak_cust").get_data(as_text=True)
        assert "/srv/mediahub" not in body
        assert "missing sheet" not in body
        # but the failure is still surfaced honestly
        assert "couldn" in body.lower() or "went wrong" in body.lower()

    def test_operator_review_shows_raw_exception(self, env):
        c, wm = env
        self._write_failed_run(wm, "errleak_op")
        with c.session_transaction() as s:
            s["dev_operator"] = True
        body = c.get("/review/errleak_op").get_data(as_text=True)
        assert "/srv/mediahub" in body
