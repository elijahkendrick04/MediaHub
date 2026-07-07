"""PC.7 — instant try-before-signup demo: caps, sandbox isolation, the
demo flow (staged upload → club pick → run → preview), claim, and sweep."""

from __future__ import annotations

import importlib
import json

import pytest


@pytest.fixture
def demo_world(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))

    import mediahub.web.club_profile as cp
    import mediahub.web.demo_try as dt
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(dt)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    return {"app": app, "wm": wm, "dt": dt, "tmp": tmp_path}


def _seed_demo_run(world, run_id, *, status="done", created_at=None):
    """A finished demo-org run with two ranked achievements."""
    dt = world["dt"]
    runs_dir = world["tmp"] / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "profile_id": dt.DEMO_PROFILE_ID,
        "meet_name": "Demo Gala",
        "meet": {"name": "Demo Gala"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "achievement": {
                        "swim_id": f"swim-{i}",
                        "swimmer_name": f"Swimmer {i}",
                        "event": "100m Freestyle",
                        "time": "59.10",
                        "type": "pb_confirmed",
                    }
                }
                for i in (1, 2)
            ]
        },
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(data))
    conn = world["wm"]._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, COALESCE(?, datetime('now')), ?, ?, ?, ?)",
        (run_id, created_at, status, dt.DEMO_PROFILE_ID, "Demo Gala", "demo.hy3"),
    )
    conn.commit()
    conn.close()


# ---- module: caps ----------------------------------------------------------


def test_caps_per_ip_and_global(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TRY_IP_DAILY_CAP", "2")
    monkeypatch.setenv("MEDIAHUB_TRY_GLOBAL_DAILY_CAP", "3")
    from mediahub.web.demo_try import claim_demo_slot

    assert claim_demo_slot("1.1.1.1") == (True, "")
    assert claim_demo_slot("1.1.1.1")[0] is True
    ok, reason = claim_demo_slot("1.1.1.1")
    assert ok is False and "limit" in reason.lower()
    # Other IP still allowed until the global cap trips.
    assert claim_demo_slot("2.2.2.2")[0] is True
    ok, reason = claim_demo_slot("3.3.3.3")
    assert ok is False  # global cap (3) reached


def test_demo_disabled_flag(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TRY_DEMO", "0")
    from mediahub.web.demo_try import demo_enabled

    assert demo_enabled() is False


def test_ensure_demo_profile_is_unbound_and_idempotent(demo_world):
    dt = demo_world["dt"]
    p1 = dt.ensure_demo_profile()
    p2 = dt.ensure_demo_profile()
    assert p1.profile_id == dt.DEMO_PROFILE_ID == p2.profile_id
    from mediahub.web.tenancy import MembershipStore

    assert MembershipStore().is_bound(dt.DEMO_PROFILE_ID) is False


# ---- routes: form + validation ----------------------------------------------


def test_try_page_public(demo_world):
    c = demo_world["app"].test_client()
    r = c.get("/try")
    assert r.status_code == 200
    assert b"results file" in r.data.lower()


def test_try_disabled_404s(demo_world, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TRY_DEMO", "0")
    c = demo_world["app"].test_client()
    assert c.get("/try").status_code == 404


def test_try_rejects_bad_extension(demo_world):
    import io

    c = demo_world["app"].test_client()
    r = c.post(
        "/try",
        data={"file": (io.BytesIO(b"x" * 10), "evil.exe")},
        content_type="multipart/form-data",
    )
    assert r.status_code == 200
    assert b"file type isn" in r.data  # "isn't" arrives HTML-escaped


def test_try_caps_enforced_on_route(demo_world, monkeypatch):
    import io

    monkeypatch.setenv("MEDIAHUB_TRY_IP_DAILY_CAP", "1")
    c = demo_world["app"].test_client()
    # First claim consumes the cap (the junk file fails the parse honestly).
    r1 = c.post(
        "/try",
        data={"file": (io.BytesIO(b"junk-bytes"), "meet.hy3")},
        content_type="multipart/form-data",
    )
    assert r1.status_code == 200
    r2 = c.post(
        "/try",
        data={"file": (io.BytesIO(b"junk-bytes"), "meet.hy3")},
        content_type="multipart/form-data",
    )
    assert b"demo limit" in r2.data or b"global limit" in r2.data


# ---- routes: start (staged → pipeline) --------------------------------------


def test_try_start_runs_pipeline_with_demo_restrictions(demo_world, monkeypatch):
    wm = demo_world["wm"]
    dt = demo_world["dt"]
    tmp = demo_world["tmp"]

    temp_id = "a" * 12
    tmp_dir = tmp / "runs_v4" / temp_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "input.bin").write_bytes(b"fake meet bytes")
    (tmp_dir / "demo_meta.json").write_text(
        json.dumps({"filename": "meet.hy3", "clubs": ["Demo SC", "Other SC"], "meet_name": "Gala"})
    )

    calls = {}

    def fake_start_run(file_bytes, file_name, profile_id, use_pb_cache, fetch_pbs, **kw):
        calls.update(
            file_name=file_name,
            profile_id=profile_id,
            fetch_pbs=fetch_pbs,
            club_filter=kw.get("club_filter"),
        )
        _seed_demo_run(demo_world, "runfake12345")
        return "runfake12345"

    monkeypatch.setattr(wm, "_start_run", fake_start_run)

    c = demo_world["app"].test_client()
    with c.session_transaction() as sess:
        sess["demo_pending"] = [temp_id]
    r = c.post("/try/start", data={"temp_id": temp_id, "club": "Demo SC"})
    assert r.status_code == 302
    assert "/try/runfake12345" in r.headers["Location"]
    # Demo restrictions: sandbox org + PB web-verification OFF.
    assert calls["profile_id"] == dt.DEMO_PROFILE_ID
    assert calls["fetch_pbs"] is False
    assert calls["club_filter"] == "Demo SC"
    with c.session_transaction() as sess:
        assert "runfake12345" in sess["demo_runs"]


def test_try_start_rejects_unstaged_or_foreign_temp(demo_world):
    c = demo_world["app"].test_client()
    r = c.post("/try/start", data={"temp_id": "b" * 12, "club": "X"})
    assert r.status_code == 404


def test_try_start_rejects_club_not_in_meet(demo_world):
    tmp = demo_world["tmp"]
    temp_id = "c" * 12
    tmp_dir = tmp / "runs_v4" / temp_id
    tmp_dir.mkdir(parents=True, exist_ok=True)
    (tmp_dir / "input.bin").write_bytes(b"x")
    (tmp_dir / "demo_meta.json").write_text(json.dumps({"filename": "m.hy3", "clubs": ["A"]}))
    c = demo_world["app"].test_client()
    with c.session_transaction() as sess:
        sess["demo_pending"] = [temp_id]
    assert c.post("/try/start", data={"temp_id": temp_id, "club": "B"}).status_code == 400


# ---- routes: results page + isolation ----------------------------------------


def test_try_results_page_and_session_isolation(demo_world):
    _seed_demo_run(demo_world, "rundone00001")
    app = demo_world["app"]

    c = app.test_client()
    with c.session_transaction() as sess:
        sess["demo_runs"] = ["rundone00001"]
    r = c.get("/try/rundone00001")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "Swimmer 1" in html
    assert "Sign up" in html
    assert "card/swim-1.png" in html

    # A different browser session can NOT see this run.
    stranger = app.test_client()
    assert stranger.get("/try/rundone00001").status_code == 404


def test_try_real_org_runs_unreachable_via_demo_routes(demo_world):
    """A run owned by a real org 404s on /try even if the id leaks into the
    session — demo routes only ever serve demo-org runs."""
    wm = demo_world["wm"]
    runs_dir = demo_world["tmp"] / "runs_v4"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "runreal00001.json").write_text(json.dumps({"profile_id": "real-org"}))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name) "
        "VALUES (?, datetime('now'), 'done', 'real-org', 'Real Meet', 'r.hy3')",
        ("runreal00001",),
    )
    conn.commit()
    conn.close()
    c = demo_world["app"].test_client()
    with c.session_transaction() as sess:
        sess["demo_runs"] = ["runreal00001"]
    assert c.get("/try/runreal00001").status_code == 404


def test_try_waiting_page_while_running(demo_world):
    _seed_demo_run(demo_world, "runwait00001", status="running")
    c = demo_world["app"].test_client()
    with c.session_transaction() as sess:
        sess["demo_runs"] = ["runwait00001"]
    r = c.get("/try/runwait00001")
    assert r.status_code == 200
    assert b"location.reload()" in r.data


def test_try_card_png_served_from_manifest(demo_world):
    _seed_demo_run(demo_world, "runpng000001")
    tmp = demo_world["tmp"]
    png = tmp / "runs_v4" / "runpng000001" / "demo.png"
    png.parent.mkdir(parents=True, exist_ok=True)
    png.write_bytes(b"\x89PNG fake")
    (tmp / "runs_v4" / "runpng000001" / "demo_cards.json").write_text(
        json.dumps({"swim-1": str(png)})
    )
    c = demo_world["app"].test_client()
    with c.session_transaction() as sess:
        sess["demo_runs"] = ["runpng000001"]
    r = c.get("/try/runpng000001/card/swim-1.png")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("image/png")
    # A card outside the top-3 preview 404s.
    assert c.get("/try/runpng000001/card/swim-99.png").status_code == 404


# ---- claim: a converting club keeps its preview -------------------------------


def test_claim_restamps_run_to_own_org(demo_world):
    from mediahub.web.club_profile import ClubProfile, save_profile

    _seed_demo_run(demo_world, "runclaim0001")
    save_profile(ClubProfile(profile_id="my-club", display_name="My Club"))

    app = demo_world["app"]
    wm = demo_world["wm"]
    c = app.test_client()
    assert c.post("/api/organisation/active", data={"profile_id": "my-club"}).status_code == 200
    with c.session_transaction() as sess:
        sess["demo_runs"] = ["runclaim0001"]

    r = c.post("/try/runclaim0001/claim")
    assert r.status_code == 302

    data = json.loads((demo_world["tmp"] / "runs_v4" / "runclaim0001.json").read_text())
    assert data["profile_id"] == "my-club"
    conn = wm._db()
    row = conn.execute("SELECT profile_id FROM runs WHERE id='runclaim0001'").fetchone()
    conn.close()
    assert row[0] == "my-club"
    # Out of the sweep's reach now.
    from mediahub.web.demo_try import list_demo_run_ids

    assert "runclaim0001" not in list_demo_run_ids()


def test_claim_signed_out_redirects_to_signup(demo_world):
    _seed_demo_run(demo_world, "runclaim0002")
    c = demo_world["app"].test_client()
    with c.session_transaction() as sess:
        sess["demo_runs"] = ["runclaim0002"]
    r = c.post("/try/runclaim0002/claim")
    assert r.status_code == 302
    assert "/signup" in r.headers["Location"]


def test_claim_db_failure_rolls_back_and_errors(demo_world, monkeypatch):
    """A failed DB re-stamp must not half-claim: the run JSON rolls back to
    the demo org (JSON and DB agree, so the sweep can't eat a claimed run)
    and the user sees an honest error instead of a silent success."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    _seed_demo_run(demo_world, "runclaim0003")
    save_profile(ClubProfile(profile_id="my-club", display_name="My Club"))

    app = demo_world["app"]
    wm = demo_world["wm"]
    dt = demo_world["dt"]
    c = app.test_client()
    assert c.post("/api/organisation/active", data={"profile_id": "my-club"}).status_code == 200
    with c.session_transaction() as sess:
        sess["demo_runs"] = ["runclaim0003"]

    real_db = wm._db

    class _FlakyConn:
        """Delegates everything except the ownership UPDATE, which fails."""

        def __init__(self, real):
            self._real = real

        def execute(self, sql, *a, **kw):
            if sql.lstrip().upper().startswith("UPDATE RUNS SET PROFILE_ID"):
                raise RuntimeError("db down")
            return self._real.execute(sql, *a, **kw)

        def __getattr__(self, name):
            return getattr(self._real, name)

    monkeypatch.setattr(wm, "_db", lambda: _FlakyConn(real_db()))
    r = c.post("/try/runclaim0003/claim")
    assert r.status_code == 500
    monkeypatch.setattr(wm, "_db", real_db)

    # JSON rolled back — still the demo org's run, matching the DB row.
    data = json.loads((demo_world["tmp"] / "runs_v4" / "runclaim0003.json").read_text())
    assert data["profile_id"] == dt.DEMO_PROFILE_ID
    conn = wm._db()
    row = conn.execute("SELECT profile_id FROM runs WHERE id='runclaim0003'").fetchone()
    conn.close()
    assert row[0] == dt.DEMO_PROFILE_ID
    # Still in the session's demo list, so the user can retry the claim.
    with c.session_transaction() as sess:
        assert "runclaim0003" in sess.get("demo_runs", [])


# ---- sweep ---------------------------------------------------------------------


def test_sweep_deletes_only_stale_demo_runs(demo_world):
    from mediahub.web.demo_try import sweep_demo_runs

    _seed_demo_run(demo_world, "runold000001", created_at="2020-01-01T00:00:00+00:00")
    _seed_demo_run(demo_world, "runnew000001")

    deleted = []

    def fake_delete(run_id):
        deleted.append(run_id)
        return True

    n = sweep_demo_runs(fake_delete, older_than_hours=24)
    assert n == 1
    assert deleted == ["runold000001"]


def test_sweep_removes_abandoned_staging_dirs(demo_world):
    """Staging dirs (upload made, club never picked) are pre-run only —
    the DB-driven sweep can't see them, so _sweep_demo_staging_dirs must:
    old marker dirs go, fresh ones and real run sidecar dirs stay."""
    import os

    wm = demo_world["wm"]
    runs_dir = demo_world["tmp"] / "runs_v4"

    old_stage = runs_dir / "aaaaaaaaaaaa"
    old_stage.mkdir(parents=True)
    (old_stage / "input.bin").write_bytes(b"x")
    (old_stage / "demo_meta.json").write_text("{}")
    stale = 1_577_836_800  # 2020-01-01 — well past 24h
    os.utime(old_stage / "demo_meta.json", (stale, stale))

    fresh_stage = runs_dir / "bbbbbbbbbbbb"
    fresh_stage.mkdir(parents=True)
    (fresh_stage / "input.bin").write_bytes(b"x")
    (fresh_stage / "demo_meta.json").write_text("{}")

    # A real run sidecar dir (no demo_meta.json) must never be touched,
    # however old.
    sidecar = runs_dir / "runreal00001"
    sidecar.mkdir(parents=True)
    (sidecar / "demo_cards.json").write_text("{}")
    os.utime(sidecar / "demo_cards.json", (stale, stale))

    n = wm._sweep_demo_staging_dirs(older_than_hours=24)
    assert n == 1
    assert not old_stage.exists()
    assert fresh_stage.exists()
    assert sidecar.exists()


def test_sweep_with_real_delete_run(demo_world):
    """End-to-end: the sweep wired to web.py's _delete_run removes the run
    JSON, sidecar dir, and DB row."""
    wm = demo_world["wm"]
    from mediahub.web.demo_try import sweep_demo_runs

    _seed_demo_run(demo_world, "runold000002", created_at="2020-01-01T00:00:00+00:00")
    runs_dir = demo_world["tmp"] / "runs_v4"
    assert (runs_dir / "runold000002.json").exists()

    n = sweep_demo_runs(wm._delete_run, older_than_hours=24)
    assert n == 1
    assert not (runs_dir / "runold000002.json").exists()
    conn = wm._db()
    row = conn.execute("SELECT id FROM runs WHERE id='runold000002'").fetchone()
    conn.close()
    assert row is None
