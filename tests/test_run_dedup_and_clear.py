"""Run de-duplication + bulk clear.

Covers:
  * the identity helpers (content hash, meet-name normalisation, fingerprint)
  * the duplicate map / duplicate lookup (same file OR same meet, per tenant)
  * the per-tenant ``/privacy/runs/clear-all`` route (multi-tenant + AJAX)
  * the delete / clear / "Re-run" UI on My Season and Activity
  * the additive schema migration (content_hash + meet_fingerprint columns)
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


def _wm():
    import mediahub.web.web as wm

    return wm


# ---------------------------------------------------------------------------
# Pure helper unit tests (no app / DB needed)
# ---------------------------------------------------------------------------


def test_content_hash_stable_and_distinct():
    wm = _wm()
    assert wm._content_hash(b"abc") == wm._content_hash(b"abc")
    assert wm._content_hash(b"abc") != wm._content_hash(b"abd")
    assert len(wm._content_hash(b"x")) == 64  # sha256 hex digest


def test_normalize_meet_name():
    n = _wm()._normalize_meet_name
    assert n("County Champs!") == n("county   champs")
    assert n("  City of Sheffield — Spring Open  ") == n("city of sheffield spring open")
    assert n("") == ""
    assert n(None) == ""


def test_meet_fingerprint_identity_org_and_date():
    fp = _wm()._meet_fingerprint
    a = fp("org1", "Spring Open", "2026-05-10")
    # Same meet, trivially different spelling + a time component on the date.
    b = fp("org1", "spring   open!", "2026-05-10T09:00:00")
    assert a and a == b
    assert fp("org2", "Spring Open", "2026-05-10") != a  # different org
    assert fp("org1", "Spring Open", "2027-05-10") != a  # different year
    assert fp("org1", "", "2026-05-10") == ""  # no name → no fingerprint


def test_duplicate_map_groups_by_hash_or_fingerprint():
    wm = _wm()
    # Newest-first, exactly as the DB queries return.
    rows = [
        {"id": "r3", "created_at": "2026-05-12", "content_hash": "H1", "meet_fingerprint": "F2"},
        {"id": "r2", "created_at": "2026-05-11", "content_hash": "H9", "meet_fingerprint": "F1"},
        {"id": "r1", "created_at": "2026-05-10", "content_hash": "H1", "meet_fingerprint": "F1"},
    ]
    dup = wm._duplicate_map(rows)
    # r1 is the oldest → the original, never flagged. r3 shares its hash, r2 its
    # fingerprint, so both are re-runs pointing back to r1 (one transitive group).
    assert "r1" not in dup
    assert dup["r2"]["original_id"] == "r1"
    assert dup["r3"]["original_id"] == "r1"
    assert dup["r2"]["count"] == 3
    assert dup["r2"]["original_date"] == "2026-05-10"


def test_duplicate_map_ignores_empty_signals():
    wm = _wm()
    rows = [
        {"id": "a", "created_at": "2026-05-11", "content_hash": "", "meet_fingerprint": ""},
        {"id": "b", "created_at": "2026-05-10", "content_hash": "", "meet_fingerprint": ""},
    ]
    assert wm._duplicate_map(rows) == {}


# ---------------------------------------------------------------------------
# App-backed tests
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path, monkeypatch):
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

    for pid, name in (("club-a", "Club A"), ("club-b", "Club B")):
        save_profile(
            ClubProfile(profile_id=pid, display_name=name, brand_voice_summary=f"{name} voice.")
        )

    with app.test_client() as c:
        yield c, wm, tmp_path


def _seed_run(
    wm,
    run_id,
    pid,
    meet,
    *,
    created_at,
    status="done",
    content_hash="",
    meet_fingerprint="",
    our_swims=5,
    n_ach=3,
):
    (Path(wm.RUNS_DIR) / f"{run_id}.json").write_text(
        json.dumps({"run_id": run_id, "profile_id": pid, "meet_name": meet})
    )
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, finished_at, status, profile_id, "
        "meet_name, our_swims, n_cards, n_queue, n_achievements, error, file_name, "
        "content_hash, meet_fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (run_id, created_at, created_at, status, pid, meet, our_swims, 0, 0, n_ach,
         None, "f.hy3", content_hash, meet_fingerprint),
    )
    conn.commit()
    conn.close()


def _pin(c, pid):
    r = c.post("/api/organisation/active", data={"profile_id": pid})
    assert r.status_code == 200, r.get_json()


def test_runs_table_has_dedup_columns(client):
    _c, wm, _ = client
    conn = wm._db()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    conn.close()
    assert "content_hash" in cols
    assert "meet_fingerprint" in cols


def test_find_duplicate_run_by_hash_and_fingerprint(client):
    _c, wm, _ = client
    _seed_run(
        wm, "orig", "club-a", "Spring Open", created_at="2026-05-10T10:00:00",
        content_hash="HASHX", meet_fingerprint="FPX",
    )
    # Exact file re-run (same hash, unrelated fingerprint).
    d = wm._find_duplicate_run("club-a", "HASHX", "OTHER")
    assert d and d["run_id"] == "orig" and d["exact"] is True
    # Same meet via a different file (different hash, same fingerprint).
    d2 = wm._find_duplicate_run("club-a", "DIFFERENT", "FPX")
    assert d2 and d2["run_id"] == "orig" and d2["exact"] is False
    # Cross-tenant isolation: another org sees nothing.
    assert wm._find_duplicate_run("club-b", "HASHX", "FPX") is None
    # Excluding the run itself returns nothing.
    assert wm._find_duplicate_run("club-a", "HASHX", "FPX", exclude_run_id="orig") is None


def test_clear_all_is_per_tenant_and_returns_json(client):
    c, wm, tmp = client
    _seed_run(wm, "a1", "club-a", "Meet A1", created_at="2026-05-10T10:00:00")
    _seed_run(wm, "a2", "club-a", "Meet A2", created_at="2026-05-11T10:00:00")
    _seed_run(wm, "b1", "club-b", "Meet B1", created_at="2026-05-10T10:00:00")
    _pin(c, "club-a")

    r = c.post("/privacy/runs/clear-all", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code == 200
    j = r.get_json()
    assert j["ok"] is True and j["deleted"] == 2

    conn = wm._db()
    n_a = conn.execute("SELECT COUNT(*) FROM runs WHERE profile_id='club-a'").fetchone()[0]
    n_b = conn.execute("SELECT COUNT(*) FROM runs WHERE profile_id='club-b'").fetchone()[0]
    conn.close()
    assert n_a == 0 and n_b == 1
    assert not (tmp / "runs_v4" / "a1.json").exists()
    assert (tmp / "runs_v4" / "b1.json").exists()  # other tenant untouched


def test_clear_all_skips_in_flight_runs(client):
    c, wm, _ = client
    _seed_run(wm, "done1", "club-a", "Done", created_at="2026-05-10T10:00:00", status="done")
    _seed_run(wm, "run1", "club-a", "Running", created_at="2026-05-11T10:00:00", status="running")
    _pin(c, "club-a")

    r = c.post("/privacy/runs/clear-all", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.get_json()["deleted"] == 1
    conn = wm._db()
    remaining = [row["id"] for row in conn.execute(
        "SELECT id FROM runs WHERE profile_id='club-a'"
    ).fetchall()]
    conn.close()
    assert remaining == ["run1"]  # the in-flight run survives


def test_clear_all_without_active_org_deletes_nothing(client):
    c, wm, _ = client
    _seed_run(wm, "x1", "club-a", "X", created_at="2026-05-10T10:00:00")
    # No _pin → no active org. The org gate redirects the POST (302) before it
    # reaches the route; in a non-gated deployment the route's own guard returns
    # 400. Either way the invariant holds: nothing is deleted.
    r = c.post("/privacy/runs/clear-all", headers={"X-Requested-With": "XMLHttpRequest"})
    assert r.status_code in (302, 400, 403)
    conn = wm._db()
    n = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conn.close()
    assert n == 1  # nothing deleted


def test_season_page_has_delete_and_clear_controls(client):
    c, wm, _ = client
    _seed_run(wm, "s1", "club-a", "Spring Open", created_at="2026-05-10T10:00:00")
    _pin(c, "club-a")
    html = c.get("/season").get_data(as_text=True)
    assert 'class="mh-run-delete"' in html
    assert 'data-run-id="s1"' in html
    assert 'class="mh-clear-all-runs"' in html
    assert "/privacy/runs/clear-all" in html


def test_activity_page_has_delete_and_clear_controls(client):
    c, wm, _ = client
    _seed_run(wm, "a1", "club-a", "Spring Open", created_at="2026-05-10T10:00:00")
    _pin(c, "club-a")
    html = c.get("/activity").get_data(as_text=True)
    assert 'class="mh-run-delete"' in html
    assert 'data-run-id="a1"' in html
    assert 'class="mh-clear-all-runs"' in html


def test_activity_shows_rerun_badge_for_duplicate(client):
    c, wm, _ = client
    # Two runs, same meet fingerprint → the newer is a re-run of the older.
    _seed_run(
        wm, "first", "club-a", "Spring Open", created_at="2026-05-10T10:00:00",
        meet_fingerprint="FP1",
    )
    _seed_run(
        wm, "second", "club-a", "Spring Open", created_at="2026-05-12T10:00:00",
        meet_fingerprint="FP1",
    )
    _pin(c, "club-a")
    html = c.get("/activity").get_data(as_text=True)
    # "Same meet already processed" is the badge's unique tooltip text (the bare
    # word "Re-run" also appears in unrelated caption-tool JS).
    assert "Same meet already processed" in html
    # The badge links back to the original run's review page.
    assert "/review/first" in html


def test_no_rerun_badge_for_distinct_meets(client):
    c, wm, _ = client
    _seed_run(
        wm, "m1", "club-a", "Spring Open", created_at="2026-05-10T10:00:00",
        meet_fingerprint="FP1",
    )
    _seed_run(
        wm, "m2", "club-a", "Autumn Gala", created_at="2026-05-12T10:00:00",
        meet_fingerprint="FP2",
    )
    _pin(c, "club-a")
    html = c.get("/activity").get_data(as_text=True)
    assert "Same meet already processed" not in html
