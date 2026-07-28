"""Follow-ups to the content-builder review (PR #1344):

1. Revisit restore covers EVERY published reel cut — the builder resolves the
   newest rendered ``reel_*.mp4`` back into file-route params (``?sel=`` names
   the selection marker, which the hash can't be reversed into), instead of
   only ever restoring the default ``reel_3`` story cut.
2. ``?sel=<hash8>`` on the reel file/manifest routes — strict vocabulary,
   ``?cards=`` wins when both are supplied.
3. A per-organisation ceiling on live background render jobs — an honest 429
   instead of unbounded queueing on the shared renderer; stale/finished jobs
   never count.
4. Job-store hygiene: orphaned ``.tmp`` save files are GC'd.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _run_payload(profile_id: str, n: int = 5) -> dict:
    return {
        "run_id": "r1",
        "profile_id": profile_id,
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": f"swim-{i + 1}",
                    "rank": i + 1,
                    "priority": 0.9 - i * 0.1,
                    "achievement": {
                        "swim_id": f"swim-{i + 1}",
                        "swimmer_name": f"Swimmer {i + 1}",
                        "event": "100m Freestyle",
                        "headline": "PB set",
                        "time": "59.80",
                    },
                }
                for i in range(n)
            ]
        },
    }


@pytest.fixture
def app_env(app, web_module, tmp_path):
    import mediahub.media_library.store as mls

    mls._default_store = None
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    save_profile(ClubProfile(profile_id="beta", display_name="Beta SC"))
    (web_module.RUNS_DIR / "r1.json").write_text(json.dumps(_run_payload("alpha")), encoding="utf-8")
    return app, web_module


class TestSelParam:
    def test_sel_serves_the_selection_suffixed_file(self, app_env):
        app, wm = app_env
        mdir = wm.RUNS_DIR / "r1" / "motion"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "reel_2_sel0badf00d.mp4").write_bytes(b"0" * 2048)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            r = c.get("/api/runs/r1/reel-file?n=2&sel=0badf00d")
            assert r.status_code == 200
            assert "video/mp4" in (r.headers.get("Content-Type") or "")

    def test_bad_sel_is_400_and_cards_wins_over_sel(self, app_env):
        app, wm = app_env
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            r = c.get("/api/runs/r1/reel-file?n=2&sel=nothex!!")
            assert r.status_code == 400
            assert r.get_json()["error"] == "bad_sel"
            # cards= re-derives its own hash — a contradictory sel= is ignored.
            r = c.get("/api/runs/r1/reel-file?n=2&sel=0badf00d&cards=swim-4,swim-2")
            assert r.status_code == 404  # derived-from-cards name, not rendered
            assert r.get_json()["error"] == "reel_not_rendered"


class TestBuilderRestoreAnyCut:
    def _pack_html(self, app, wm, tmp_path):
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore

        ws = WorkflowStore(Path(tmp_path / "runs_v4"))
        for i in range(1, 4):
            ws.set_status("r1", f"swim-{i}", CardStatus.APPROVED)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            resp = c.get("/pack/r1")
        assert resp.status_code == 200
        return resp.get_data(as_text=True)

    def test_newest_custom_cut_wins_the_restore(self, app_env, tmp_path):
        app, wm = app_env
        mdir = wm.RUNS_DIR / "r1" / "motion"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "reel_3.mp4").write_bytes(b"0" * 2048)
        custom = mdir / "reel_2_sel0badf00d_portrait.mp4"
        custom.write_bytes(b"0" * 2048)
        import os

        _now = time.time()
        os.utime(mdir / "reel_3.mp4", (_now - 600, _now - 600))
        os.utime(custom, (_now, _now))
        html = self._pack_html(app, wm, tmp_path)
        assert "sel=0badf00d" in html
        assert "n=2" in html
        assert 'var restoreFmt = "portrait"' in html

    def test_default_cut_restores_and_tmpl_previews_are_skipped(self, app_env, tmp_path):
        app, wm = app_env
        mdir = wm.RUNS_DIR / "r1" / "motion"
        mdir.mkdir(parents=True, exist_ok=True)
        (mdir / "reel_3.mp4").write_bytes(b"0" * 2048)
        newer_preview = mdir / "reel_3_tmpl0badf00d.mp4"
        newer_preview.write_bytes(b"0" * 2048)
        html = self._pack_html(app, wm, tmp_path)
        assert "reel-file?n=3" in html
        assert "tmpl" not in html.split("var restoreUrl = ")[1][:200]

    def test_no_rendered_reel_means_no_restore_url(self, app_env, tmp_path):
        app, wm = app_env
        html = self._pack_html(app, wm, tmp_path)
        assert 'var restoreUrl = ""' in html


class TestRenderJobQuota:
    def _seed_running_jobs(self, wm, pid: str, n: int, *, kind: str = "reel", stale: bool = False):
        jdir = wm._variant_jobs_dir()
        jdir.mkdir(parents=True, exist_ok=True)
        ts = time.time() - (wm._VARIANT_JOB_STALL_S + 60 if stale else 0)
        for i in range(n):
            jid = f"{i:032x}"
            (jdir / f"{jid}.json").write_text(
                json.dumps(
                    {
                        "id": jid,
                        "kind": kind,
                        "status": "running",
                        "owner_pid": pid,
                        "created_at": ts,
                        "updated_at": ts,
                    }
                ),
                encoding="utf-8",
            )

    def test_at_cap_job_start_is_429(self, app_env, monkeypatch):
        app, wm = app_env
        self._seed_running_jobs(wm, "alpha", wm._RENDER_JOBS_PER_ORG_CAP)
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            r = c.post("/api/runs/r1/reel-job")
            assert r.status_code == 429
            body = r.get_json()
            assert body["error"] == "render_jobs_capped"
            assert "wait" in (body.get("user_message") or "").lower()

    def test_other_org_and_stale_jobs_never_count(self, app_env):
        app, wm = app_env
        # A full cap of SOMEONE ELSE's jobs plus a full cap of stale own jobs.
        self._seed_running_jobs(wm, "beta", wm._RENDER_JOBS_PER_ORG_CAP)
        jdir = wm._variant_jobs_dir()
        ts = time.time() - (wm._VARIANT_JOB_STALL_S + 60)
        for i in range(10, 10 + wm._RENDER_JOBS_PER_ORG_CAP):
            jid = f"{i:032x}"
            (jdir / f"{jid}.json").write_text(
                json.dumps(
                    {
                        "id": jid,
                        "kind": "reel",
                        "status": "running",
                        "owner_pid": "alpha",
                        "created_at": ts,
                        "updated_at": ts,
                    }
                ),
                encoding="utf-8",
            )
        with app.test_client() as c:
            c.post("/api/organisation/active", data={"profile_id": "alpha"})
            assert wm._render_job_quota_denied() is None


class TestJobStoreHygiene:
    def test_gc_removes_stale_tmp_files(self, app_env):
        app, wm = app_env
        jdir = wm._variant_jobs_dir()
        jdir.mkdir(parents=True, exist_ok=True)
        import os

        stale = jdir / "deadbeef.abc123.tmp"
        stale.write_text("{}", encoding="utf-8")
        old = time.time() - 7200
        os.utime(stale, (old, old))
        fresh = jdir / "cafebabe.def456.tmp"
        fresh.write_text("{}", encoding="utf-8")
        wm._variant_jobs_gc()
        assert not stale.exists()
        assert fresh.exists()
